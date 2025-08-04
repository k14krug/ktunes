"""
Duplicate Detection Service for identifying and analyzing duplicate songs.

This service provides functionality to detect songs that appear multiple times
with variations in their titles or artist names, such as remaster suffixes,
version numbers, or other appended text.
"""

import re
import difflib
import time
import uuid
import logging
import threading
import signal
import traceback
import gc
import psutil
import os
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Callable, Iterator
from dataclasses import dataclass
from contextlib import contextmanager
from models import Track
from extensions import db
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError, OperationalError, IntegrityError


@dataclass
class DuplicateGroup:
    """Data transfer object for a group of duplicate songs."""
    canonical_song: Track
    duplicates: List[Track]
    similarity_scores: Dict[int, float]  # track_id -> similarity score
    suggested_action: str  # 'keep_most_played', 'keep_canonical', etc.


@dataclass
class DuplicateAnalysis:
    """Data transfer object for overall duplicate analysis results."""
    total_groups: int
    total_duplicates: int
    potential_deletions: int
    estimated_space_savings: str
    groups_with_high_confidence: int
    average_similarity_score: float


@dataclass
class AnalysisProgress:
    """Data class for structured progress information during duplicate analysis."""
    analysis_id: str
    status: str  # 'starting', 'loading_tracks', 'analyzing_similarities', 'cross_referencing', 'saving_results', 'completed', 'failed', 'cancelled'
    phase: str
    current_step: int
    total_steps: int
    percentage: float
    estimated_remaining_seconds: Optional[int]
    current_message: str
    tracks_processed: int
    total_tracks: int
    groups_found: int
    start_time: datetime
    last_update: datetime
    error_message: Optional[str] = None


class AnalysisTimeoutError(Exception):
    """Raised when analysis times out."""
    pass


class AnalysisCancelledException(Exception):
    """Raised when analysis is cancelled by user."""
    pass


class DuplicateDetectionService:
    """Service for detecting and analyzing duplicate songs in the music library."""
    
    # Error handling and timeout configuration
    DEFAULT_TIMEOUT_SECONDS = 300  # 5 minutes
    MAX_RETRY_ATTEMPTS = 3
    RETRY_DELAY_SECONDS = 2
    CHECKPOINT_INTERVAL = 100  # Save progress every 100 tracks
    
    # Memory management and performance configuration
    STREAMING_BATCH_SIZE = 1000  # Process tracks in batches for large datasets
    MAX_MEMORY_USAGE_MB = 512  # Maximum memory usage before triggering cleanup
    MEMORY_CHECK_INTERVAL = 50  # Check memory usage every N tracks
    GC_COLLECTION_INTERVAL = 200  # Force garbage collection every N tracks
    REQUEST_TIMEOUT_SECONDS = 30  # Timeout for individual database requests
    
    # Common suffix patterns that indicate variations of the same song
    SUFFIX_PATTERNS = [
        r'\s*-\s*\d{4}\s*remaster(?:ed)?',
        r'\s*-\s*remaster(?:ed)?(?:\s*\d{4})?',
        r'\s*-\s*deluxe\s*(?:edition|version)?',
        r'\s*-\s*radio\s*edit',
        r'\s*-\s*extended\s*(?:version|mix)?',
        r'\s*-\s*single\s*(?:version|edit)?',
        r'\s*-\s*album\s*version',
        r'\s*-\s*live\s*(?:version)?',
        r'\s*-\s*acoustic\s*(?:version)?',
        r'\s*-\s*instrumental',
        r'\s*-\s*explicit\s*(?:version)?',
        r'\s*-\s*clean\s*(?:version)?',
        r'\s*\((?:feat|featuring)\.?\s+[^)]+\)',
        r'\s*\(remaster(?:ed)?(?:\s*\d{4})?\)',
        r'\s*\(deluxe\s*(?:edition|version)?\)',
        r'\s*\(radio\s*edit\)',
        r'\s*\(extended\s*(?:version|mix)?\)',
        r'\s*\(single\s*(?:version|edit)?\)',
        r'\s*\(album\s*version\)',
        r'\s*\(live\s*(?:version)?\)',
        r'\s*\(acoustic\s*(?:version)?\)',
        r'\s*\(instrumental\)',
        r'\s*\(explicit\s*(?:version)?\)',
        r'\s*\(clean\s*(?:version)?\)',
    ]
    
    # Minimum similarity threshold for considering songs as duplicates
    SIMILARITY_THRESHOLD = 0.8
    
    def __init__(self):
        """Initialize the duplicate detection service."""
        self.compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.SUFFIX_PATTERNS]
        self.logger = logging.getLogger(__name__)
        
        # Analysis state tracking
        self._active_analyses = {}  # analysis_id -> analysis state
        self._cancelled_analyses = set()  # Set of cancelled analysis IDs
        
        # Load configuration
        from services.error_handling_config import get_error_handling_config
        self.config = get_error_handling_config()
        
        # Error handling configuration
        self.timeout_seconds = self.config.get_timeout_seconds()
        self.max_retry_attempts = self.config.get_max_retry_attempts()
        self.retry_delay = self.config.get_retry_delay_seconds()
        
        # Memory management configuration
        self.streaming_batch_size = self.config.get_streaming_batch_size()
        self.max_memory_usage_mb = self.config.get_max_memory_usage_mb()
        self.memory_check_interval = self.config.get_memory_check_interval()
        self.gc_collection_interval = self.config.get_gc_collection_interval()
        self.checkpoint_interval = self.config.get_checkpoint_interval()
        self.request_timeout_seconds = self.config.get_request_timeout_seconds()
    
    def normalize_string(self, text: str) -> str:
        """
        Normalize a string by removing common suffixes and variations.
        
        Args:
            text: The string to normalize
            
        Returns:
            Normalized string with suffixes removed
        """
        if not text:
            return ""
        
        normalized = text.strip()
        
        # Remove common suffixes using compiled patterns
        for pattern in self.compiled_patterns:
            normalized = pattern.sub('', normalized)
        
        # Remove extra whitespace and convert to lowercase for comparison
        normalized = re.sub(r'\s+', ' ', normalized).strip().lower()
        
        return normalized
    
    def get_similarity_score(self, song1: Track, song2: Track) -> float:
        """
        Calculate similarity score between two songs based on title and artist.
        
        Args:
            song1: First song to compare
            song2: Second song to compare
            
        Returns:
            Similarity score between 0.0 and 1.0
        """
        if not song1 or not song2:
            return 0.0
        
        # Normalize song titles and artist names
        title1 = self.normalize_string(song1.song or "")
        title2 = self.normalize_string(song2.song or "")
        artist1 = self.normalize_string(song1.artist or "")
        artist2 = self.normalize_string(song2.artist or "")
        
        # Calculate similarity for titles and artists separately
        title_similarity = difflib.SequenceMatcher(None, title1, title2).ratio()
        artist_similarity = difflib.SequenceMatcher(None, artist1, artist2).ratio()
        
        # Weight title similarity more heavily than artist similarity
        # since we're primarily looking for song duplicates
        combined_similarity = (title_similarity * 0.7) + (artist_similarity * 0.3)
        
        return combined_similarity
    
    def detect_suffix_variations(self, song1: Track, song2: Track) -> bool:
        """
        Check if two songs are likely the same with suffix variations.
        
        Args:
            song1: First song to compare
            song2: Second song to compare
            
        Returns:
            True if songs appear to be suffix variations of each other
        """
        if not song1 or not song2 or not song1.song or not song2.song:
            return False
        
        # Check if artists are similar enough
        if song1.artist and song2.artist:
            artist_similarity = difflib.SequenceMatcher(
                None, 
                song1.artist.lower().strip(), 
                song2.artist.lower().strip()
            ).ratio()
            if artist_similarity < 0.9:  # Artists should be very similar
                return False
        
        # Normalize both titles
        normalized1 = self.normalize_string(song1.song)
        normalized2 = self.normalize_string(song2.song)
        
        # Check if normalized titles are very similar
        normalized_similarity = difflib.SequenceMatcher(None, normalized1, normalized2).ratio()
        
        return normalized_similarity >= 0.95
    
    def suggest_canonical_version(self, songs: List[Track]) -> Track:
        """
        Suggest which version should be kept as the canonical version.
        
        Args:
            songs: List of duplicate songs
            
        Returns:
            The suggested canonical version
        """
        if not songs:
            return None
        
        if len(songs) == 1:
            return songs[0]
        
        # Scoring criteria (higher is better):
        # 1. Play count (40% weight)
        # 2. Shorter title (less likely to have suffixes) (30% weight)
        # 3. More recent last played date (20% weight)
        # 4. Earlier date added (10% weight)
        
        best_song = songs[0]
        best_score = 0
        
        for song in songs:
            score = 0
            
            # Play count score (normalize to 0-100)
            play_count = song.play_cnt or 0
            max_play_count = max((s.play_cnt or 0) for s in songs)
            if max_play_count > 0:
                score += (play_count / max_play_count) * 40
            
            # Title length score (shorter is better)
            title_length = len(song.song or "")
            min_title_length = min(len(s.song or "") for s in songs)
            max_title_length = max(len(s.song or "") for s in songs)
            if max_title_length > min_title_length:
                length_score = 1 - ((title_length - min_title_length) / (max_title_length - min_title_length))
                score += length_score * 30
            else:
                score += 30  # All titles same length
            
            # Last played recency score
            if song.last_play_dt:
                # Find the most recent last_play_dt among all songs
                recent_dates = [s.last_play_dt for s in songs if s.last_play_dt]
                if recent_dates:
                    most_recent = max(recent_dates)
                    oldest = min(recent_dates)
                    if most_recent != oldest:
                        days_diff = (most_recent - oldest).days
                        song_days_diff = (most_recent - song.last_play_dt).days
                        recency_score = 1 - (song_days_diff / days_diff) if days_diff > 0 else 1
                        score += recency_score * 20
                    else:
                        score += 20  # All same date
            
            # Date added score (earlier is better for "original" version)
            if song.date_added:
                added_dates = [s.date_added for s in songs if s.date_added]
                if added_dates:
                    earliest = min(added_dates)
                    latest = max(added_dates)
                    if latest != earliest:
                        days_diff = (latest - earliest).days
                        song_days_diff = (song.date_added - earliest).days
                        earliness_score = 1 - (song_days_diff / days_diff) if days_diff > 0 else 1
                        score += earliness_score * 10
                    else:
                        score += 10  # All same date
            
            if score > best_score:
                best_score = score
                best_song = song
        
        return best_song
    
    def find_duplicates(self, search_term: Optional[str] = None, sort_by: str = 'artist', min_confidence: float = 0.0, use_cache: bool = True) -> List[DuplicateGroup]:
        """
        Find all duplicate songs in the database with caching support.
        
        Args:
            search_term: Optional search term to filter results
            sort_by: Field to sort results by ('artist', 'song', 'duplicates')
            min_confidence: Minimum confidence threshold for including groups
            use_cache: Whether to use cached results if available
            
        Returns:
            List of DuplicateGroup objects
        """
        # Check cache first if enabled
        if use_cache:
            from services.duplicate_cache_service import get_duplicate_cache
            cache_service = get_duplicate_cache()
            cached_result = cache_service.get_cached_duplicates(search_term, sort_by, min_confidence)
            if cached_result is not None:
                return cached_result
        
        # Get all tracks from database with optimized query
        query = db.session.query(Track)
        
        if search_term:
            search_pattern = f"%{search_term}%"
            query = query.filter(
                db.or_(
                    Track.song.ilike(search_pattern),
                    Track.artist.ilike(search_pattern)
                )
            )
        
        # Add query hints for better performance
        all_tracks = query.all()
        
        if not all_tracks:
            return []
        
        # Group tracks by similarity
        duplicate_groups = []
        processed_tracks = set()
        
        for i, track1 in enumerate(all_tracks):
            if track1.id in processed_tracks:
                continue
            
            # Find all similar tracks
            similar_tracks = [track1]
            similarity_scores = {track1.id: 1.0}
            
            for j, track2 in enumerate(all_tracks[i+1:], i+1):
                if track2.id in processed_tracks:
                    continue
                
                # Check similarity
                similarity = self.get_similarity_score(track1, track2)
                is_suffix_variation = self.detect_suffix_variations(track1, track2)
                
                if similarity >= self.SIMILARITY_THRESHOLD or is_suffix_variation:
                    similar_tracks.append(track2)
                    similarity_scores[track2.id] = similarity
                    processed_tracks.add(track2.id)
            
            # Only create a group if we found duplicates
            if len(similar_tracks) > 1:
                # Check if group meets minimum confidence threshold
                if min_confidence > 0.0:
                    avg_confidence = sum(similarity_scores.values()) / len(similarity_scores)
                    if avg_confidence < min_confidence:
                        # Mark tracks as processed but don't add to groups
                        for track in similar_tracks:
                            processed_tracks.add(track.id)
                        continue
                
                canonical = self.suggest_canonical_version(similar_tracks)
                duplicates = [t for t in similar_tracks if t.id != canonical.id]
                
                duplicate_group = DuplicateGroup(
                    canonical_song=canonical,
                    duplicates=duplicates,
                    similarity_scores=similarity_scores,
                    suggested_action='keep_canonical'
                )
                duplicate_groups.append(duplicate_group)
                
                # Mark all tracks in this group as processed
                for track in similar_tracks:
                    processed_tracks.add(track.id)
            else:
                processed_tracks.add(track1.id)
        
        # Sort results
        if sort_by == 'artist':
            duplicate_groups.sort(key=lambda g: (g.canonical_song.artist or "").lower())
        elif sort_by == 'song':
            duplicate_groups.sort(key=lambda g: (g.canonical_song.song or "").lower())
        elif sort_by == 'duplicates':
            duplicate_groups.sort(key=lambda g: len(g.duplicates), reverse=True)
        elif sort_by == 'confidence':
            duplicate_groups.sort(key=lambda g: sum(g.similarity_scores.values()) / len(g.similarity_scores), reverse=True)
        elif sort_by == 'play_count':
            duplicate_groups.sort(key=lambda g: g.canonical_song.play_cnt or 0, reverse=True)
        elif sort_by == 'last_played':
            duplicate_groups.sort(key=lambda g: g.canonical_song.last_play_dt or '1900-01-01', reverse=True)
        elif sort_by == 'date_added':
            duplicate_groups.sort(key=lambda g: g.canonical_song.date_added or '1900-01-01', reverse=True)
        
        # Cache the results if caching is enabled
        if use_cache:
            from services.duplicate_cache_service import get_duplicate_cache
            cache_service = get_duplicate_cache()
            cache_service.cache_duplicates(duplicate_groups, search_term, sort_by, min_confidence)
        
        return duplicate_groups
    
    def analyze_duplicate_group(self, songs: List[Track]) -> Dict:
        """
        Analyze a group of duplicate songs and provide detailed information.
        
        Args:
            songs: List of songs to analyze
            
        Returns:
            Dictionary with analysis results
        """
        if not songs:
            return {}
        
        analysis = {
            'total_songs': len(songs),
            'canonical_suggestion': self.suggest_canonical_version(songs),
            'play_count_stats': {
                'total': sum(s.play_cnt or 0 for s in songs),
                'max': max(s.play_cnt or 0 for s in songs),
                'min': min(s.play_cnt or 0 for s in songs),
                'avg': sum(s.play_cnt or 0 for s in songs) / len(songs)
            },
            'date_range': {
                'earliest_added': min(s.date_added for s in songs if s.date_added) if any(s.date_added for s in songs) else None,
                'latest_added': max(s.date_added for s in songs if s.date_added) if any(s.date_added for s in songs) else None,
                'last_played': max(s.last_play_dt for s in songs if s.last_play_dt) if any(s.last_play_dt for s in songs) else None
            },
            'title_variations': [s.song for s in songs if s.song],
            'similarity_matrix': {}
        }
        
        # Calculate similarity matrix
        for i, song1 in enumerate(songs):
            for j, song2 in enumerate(songs):
                if i != j:
                    key = f"{song1.id}-{song2.id}"
                    analysis['similarity_matrix'][key] = self.get_similarity_score(song1, song2)
        
        return analysis
    
    def get_overall_analysis(self, duplicate_groups: List[DuplicateGroup]) -> DuplicateAnalysis:
        """
        Analyze overall duplicate statistics across all groups.
        
        Args:
            duplicate_groups: List of duplicate groups to analyze
            
        Returns:
            DuplicateAnalysis object with overall statistics
        """
        if not duplicate_groups:
            return DuplicateAnalysis(
                total_groups=0,
                total_duplicates=0,
                potential_deletions=0,
                estimated_space_savings="0 MB",
                groups_with_high_confidence=0,
                average_similarity_score=0.0
            )
        
        total_duplicates = sum(len(group.duplicates) for group in duplicate_groups)
        potential_deletions = total_duplicates  # We can delete all duplicates, keeping canonical
        
        # Calculate high confidence groups (average similarity > 0.9)
        high_confidence_groups = 0
        total_similarity_scores = []
        
        for group in duplicate_groups:
            if group.similarity_scores:
                scores = list(group.similarity_scores.values())
                avg_score = sum(scores) / len(scores)
                total_similarity_scores.extend(scores)
                
                if avg_score > 0.9:
                    high_confidence_groups += 1
        
        average_similarity = (
            sum(total_similarity_scores) / len(total_similarity_scores)
            if total_similarity_scores else 0.0
        )
        
        # Rough estimate of space savings (assuming average 4MB per song)
        estimated_mb = potential_deletions * 4
        if estimated_mb > 1024:
            estimated_space = f"{estimated_mb / 1024:.1f} GB"
        else:
            estimated_space = f"{estimated_mb} MB"
        
        return DuplicateAnalysis(
            total_groups=len(duplicate_groups),
            total_duplicates=total_duplicates,
            potential_deletions=potential_deletions,
            estimated_space_savings=estimated_space,
            groups_with_high_confidence=high_confidence_groups,
            average_similarity_score=average_similarity
        )
    
    def get_duplicate_recommendations(self, duplicate_group: DuplicateGroup) -> Dict[str, any]:
        """
        Get recommendations for handling a specific duplicate group.
        
        Args:
            duplicate_group: The duplicate group to analyze
            
        Returns:
            Dictionary with recommendations and reasoning
        """
        all_songs = [duplicate_group.canonical_song] + duplicate_group.duplicates
        
        recommendations = {
            'keep_canonical': {
                'song': duplicate_group.canonical_song,
                'reason': 'Suggested canonical version based on play count, title length, and recency',
                'confidence': 'high'
            },
            'delete_candidates': [],
            'manual_review_needed': False,
            'risk_level': 'low'
        }
        
        # Analyze each duplicate for deletion recommendation
        for duplicate in duplicate_group.duplicates:
            similarity_score = duplicate_group.similarity_scores.get(duplicate.id, 0.0)
            
            delete_recommendation = {
                'song': duplicate,
                'similarity_score': similarity_score,
                'reasons': []
            }
            
            # Add reasons for deletion
            if similarity_score > 0.95:
                delete_recommendation['reasons'].append('Very high similarity to canonical version')
            elif similarity_score > 0.85:
                delete_recommendation['reasons'].append('High similarity to canonical version')
            else:
                delete_recommendation['reasons'].append('Moderate similarity - consider manual review')
                recommendations['manual_review_needed'] = True
                recommendations['risk_level'] = 'medium'
            
            # Compare play counts
            canonical_plays = duplicate_group.canonical_song.play_cnt or 0
            duplicate_plays = duplicate.play_cnt or 0
            
            if duplicate_plays == 0:
                delete_recommendation['reasons'].append('Never played')
            elif duplicate_plays < canonical_plays * 0.1:
                delete_recommendation['reasons'].append('Rarely played compared to canonical version')
            elif duplicate_plays > canonical_plays:
                delete_recommendation['reasons'].append('WARNING: More plays than canonical version')
                recommendations['manual_review_needed'] = True
                recommendations['risk_level'] = 'high'
            
            # Check title length (longer titles often have suffixes)
            canonical_length = len(duplicate_group.canonical_song.song or "")
            duplicate_length = len(duplicate.song or "")
            
            if duplicate_length > canonical_length * 1.2:
                delete_recommendation['reasons'].append('Longer title suggests variant/remaster')
            
            recommendations['delete_candidates'].append(delete_recommendation)
        
        return recommendations
    
    def find_duplicates_optimized(self, search_term: Optional[str] = None, sort_by: str = 'artist', 
                                min_confidence: float = 0.0, limit: Optional[int] = None) -> List[DuplicateGroup]:
        """
        Optimized version of find_duplicates for better performance with large datasets.
        
        Args:
            search_term: Optional search term to filter results
            sort_by: Field to sort results by
            min_confidence: Minimum confidence threshold for including groups
            limit: Maximum number of groups to process (for performance)
            
        Returns:
            List of DuplicateGroup objects
        """
        # Get tracks with optimized query
        query = db.session.query(Track)
        
        if search_term:
            search_pattern = f"%{search_term}%"
            query = query.filter(
                db.or_(
                    Track.song.ilike(search_pattern),
                    Track.artist.ilike(search_pattern)
                )
            )
        
        # Add basic ordering to improve query performance
        if sort_by == 'artist':
            query = query.order_by(Track.artist, Track.song)
        elif sort_by == 'song':
            query = query.order_by(Track.song, Track.artist)
        elif sort_by == 'play_count':
            query = query.order_by(Track.play_cnt.desc().nullslast())
        elif sort_by == 'last_played':
            query = query.order_by(Track.last_play_dt.desc().nullslast())
        elif sort_by == 'date_added':
            query = query.order_by(Track.date_added.desc().nullslast())
        
        # Limit initial query size for performance
        if limit:
            query = query.limit(limit * 2)  # Get more than needed for duplicate detection
        
        all_tracks = query.all()
        
        if not all_tracks:
            return []
        
        # Use more efficient duplicate detection for large datasets
        duplicate_groups = []
        processed_tracks = set()
        groups_found = 0
        
        for i, track1 in enumerate(all_tracks):
            if track1.id in processed_tracks:
                continue
            
            # Early exit if we've found enough groups
            if limit and groups_found >= limit:
                break
            
            # Find all similar tracks with optimized comparison
            similar_tracks = [track1]
            similarity_scores = {track1.id: 1.0}
            
            # Only compare with remaining tracks to avoid duplicate work
            for track2 in all_tracks[i+1:]:
                if track2.id in processed_tracks:
                    continue
                
                # Quick pre-filter: check if artists are similar enough
                if track1.artist and track2.artist:
                    artist_diff = abs(len(track1.artist) - len(track2.artist))
                    if artist_diff > 10:  # Skip if artist names are very different in length
                        continue
                
                # Check similarity
                similarity = self.get_similarity_score(track1, track2)
                is_suffix_variation = self.detect_suffix_variations(track1, track2)
                
                if similarity >= self.SIMILARITY_THRESHOLD or is_suffix_variation:
                    similar_tracks.append(track2)
                    similarity_scores[track2.id] = similarity
                    processed_tracks.add(track2.id)
            
            # Only create a group if we found duplicates
            if len(similar_tracks) > 1:
                # Check if group meets minimum confidence threshold
                if min_confidence > 0.0:
                    avg_confidence = sum(similarity_scores.values()) / len(similarity_scores)
                    if avg_confidence < min_confidence:
                        # Mark tracks as processed but don't add to groups
                        for track in similar_tracks:
                            processed_tracks.add(track.id)
                        continue
                
                canonical = self.suggest_canonical_version(similar_tracks)
                duplicates = [t for t in similar_tracks if t.id != canonical.id]
                
                duplicate_group = DuplicateGroup(
                    canonical_song=canonical,
                    duplicates=duplicates,
                    similarity_scores=similarity_scores,
                    suggested_action='keep_canonical'
                )
                duplicate_groups.append(duplicate_group)
                groups_found += 1
                
                # Mark all tracks in this group as processed
                for track in similar_tracks:
                    processed_tracks.add(track.id)
            else:
                processed_tracks.add(track1.id)
        
        # Apply final sorting if needed (groups are already roughly sorted due to query ordering)
        if sort_by == 'duplicates':
            duplicate_groups.sort(key=lambda g: len(g.duplicates), reverse=True)
        elif sort_by == 'confidence':
            duplicate_groups.sort(key=lambda g: sum(g.similarity_scores.values()) / len(g.similarity_scores), reverse=True)
        
        return duplicate_groups
    
    def get_overall_analysis(self, duplicate_groups: List[DuplicateGroup]) -> DuplicateAnalysis:
        """
        Get overall analysis of duplicate groups for statistics display.
        
        Args:
            duplicate_groups: List of duplicate groups to analyze
            
        Returns:
            DuplicateAnalysis object with statistics
        """
        if not duplicate_groups:
            return DuplicateAnalysis(
                total_groups=0,
                total_duplicates=0,
                potential_deletions=0,
                estimated_space_savings="0 MB",
                groups_with_high_confidence=0,
                average_similarity_score=0.0
            )
        
        total_groups = len(duplicate_groups)
        total_duplicates = sum(len(group.duplicates) for group in duplicate_groups)
        potential_deletions = total_duplicates  # All duplicates can potentially be deleted
        
        # Calculate high confidence groups (>= 90% average similarity)
        groups_with_high_confidence = 0
        total_similarity = 0
        similarity_count = 0
        
        for group in duplicate_groups:
            if group.similarity_scores:
                avg_similarity = sum(group.similarity_scores.values()) / len(group.similarity_scores)
                total_similarity += avg_similarity
                similarity_count += 1
                
                if avg_similarity >= 0.9:
                    groups_with_high_confidence += 1
        
        average_similarity_score = total_similarity / similarity_count if similarity_count > 0 else 0.0
        
        # Estimate space savings (rough calculation based on average file size)
        # Assuming average song file size of 4MB
        estimated_mb = potential_deletions * 4
        if estimated_mb >= 1024:
            estimated_space_savings = f"{estimated_mb / 1024:.1f} GB"
        else:
            estimated_space_savings = f"{estimated_mb} MB"
        
        return DuplicateAnalysis(
            total_groups=total_groups,
            total_duplicates=total_duplicates,
            potential_deletions=potential_deletions,
            estimated_space_savings=estimated_space_savings,
            groups_with_high_confidence=groups_with_high_confidence,
            average_similarity_score=average_similarity_score
        )
    
    def find_duplicates_with_timeout(self, search_term: Optional[str] = None, sort_by: str = 'artist', 
                                   min_confidence: float = 0.0, timeout_seconds: int = 30) -> Dict:
        """
        Find duplicates with timeout support for long-running operations.
        Uses threading-based timeout instead of signals for Flask compatibility.
        
        Args:
            search_term: Optional search term to filter results
            sort_by: Field to sort results by
            min_confidence: Minimum confidence threshold
            timeout_seconds: Maximum time to spend on operation
            
        Returns:
            Dictionary with results and metadata
        """
        start_time = time.time()
        
        try:
            # Use the regular find_duplicates method
            duplicate_groups = self.find_duplicates(search_term, sort_by, min_confidence)
            processing_time = time.time() - start_time
            
            # Check if we exceeded the timeout
            if processing_time > timeout_seconds:
                return {
                    'success': False,
                    'duplicate_groups': [],
                    'processing_time': processing_time,
                    'timeout_seconds': timeout_seconds,
                    'timed_out': True,
                    'error': f'Operation timed out after {processing_time:.1f} seconds'
                }
            
            return {
                'success': True,
                'duplicate_groups': duplicate_groups,
                'processing_time': processing_time,
                'timeout_seconds': timeout_seconds,
                'timed_out': False
            }
            
        except Exception as e:
            processing_time = time.time() - start_time
            return {
                'success': False,
                'duplicate_groups': [],
                'processing_time': processing_time,
                'timeout_seconds': timeout_seconds,
                'timed_out': False,
                'error': str(e)
            }
    
    def get_database_performance_stats(self) -> Dict:
        """
        Get database performance statistics for optimization.
        
        Returns:
            Dictionary with performance statistics
        """
        try:
            # Get table statistics
            track_count_result = db.session.execute(text("SELECT COUNT(*) FROM tracks")).fetchone()
            track_count = track_count_result[0] if track_count_result else 0
            
            # Check if indexes exist
            index_check_queries = [
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='tracks' AND name LIKE '%song%'",
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='tracks' AND name LIKE '%artist%'",
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='tracks' AND name LIKE '%play_cnt%'"
            ]
            
            indexes = []
            for query in index_check_queries:
                result = db.session.execute(text(query)).fetchall()
                indexes.extend([row[0] for row in result])
            
            return {
                'total_tracks': track_count,
                'available_indexes': indexes,
                'index_count': len(indexes),
                'performance_optimized': len(indexes) >= 3  # We expect at least 3 indexes
            }
            
        except Exception as e:
            return {
                'total_tracks': 0,
                'available_indexes': [],
                'index_count': 0,
                'performance_optimized': False,
                'error': str(e)
            }
    
    def invalidate_caches(self) -> None:
        """Invalidate all caches when tracks are modified."""
        try:
            from services.duplicate_cache_service import get_duplicate_cache
            cache_service = get_duplicate_cache()
            cache_service.invalidate_cache()
        except ImportError:
            pass  # Cache service not available
    
    # Class-level storage for analysis progress (in-memory)
    _analysis_progress: Dict[str, AnalysisProgress] = {}
    _progress_lock = threading.Lock()
    
    def find_duplicates_with_persistence(self, search_term: Optional[str] = None, 
                                       sort_by: str = 'artist', 
                                       min_confidence: float = 0.0,
                                       user_id: int = None,
                                       force_refresh: bool = False,
                                       progress_callback: Optional[Callable] = None,
                                       timeout_seconds: int = None) -> Dict:
        """
        Find duplicates with automatic persistence, progress tracking, and comprehensive error handling.
        
        Args:
            search_term: Optional search term to filter results
            sort_by: Field to sort results by
            min_confidence: Minimum confidence threshold
            user_id: ID of the user performing the analysis
            force_refresh: Whether to force a new analysis even if recent results exist
            progress_callback: Optional callback function for progress updates
            timeout_seconds: Custom timeout in seconds (uses default if None)
            
        Returns:
            Dict containing analysis_id, duplicate_groups, and metadata
        """
        # Generate unique analysis ID
        analysis_id = str(uuid.uuid4())
        start_time = datetime.now()
        
        # Initialize analysis state tracking
        self._active_analyses[analysis_id] = {
            'start_time': start_time,
            'user_id': user_id,
            'status': 'starting',
            'partial_groups': [],
            'checkpoint': None
        }
        
        # Initialize progress tracking
        progress = AnalysisProgress(
            analysis_id=analysis_id,
            status='starting',
            phase='Initializing analysis',
            current_step=0,
            total_steps=100,
            percentage=0.0,
            estimated_remaining_seconds=None,
            current_message='Starting duplicate analysis...',
            tracks_processed=0,
            total_tracks=0,
            groups_found=0,
            start_time=start_time,
            last_update=start_time
        )
        
        # Store progress in memory
        with self._progress_lock:
            self._analysis_progress[analysis_id] = progress
        
        # Set up logging
        logger = logging.getLogger(__name__)
        logger.info(f"Analysis {analysis_id}: Starting duplicate analysis for user {user_id}")
        
        try:
            # Use timeout handler for the entire analysis
            with self.timeout_handler(analysis_id, timeout_seconds):
                
                # Check if we should use existing results (unless force_refresh is True)
                if not force_refresh and user_id:
                    self.check_cancellation(analysis_id)
                    self.check_timeout(analysis_id)
                    
                    def get_existing_analysis():
                        from services.duplicate_persistence_service import DuplicatePersistenceService
                        persistence_service = DuplicatePersistenceService()
                        return persistence_service.get_latest_analysis(user_id, search_term)
                    
                    existing_analysis = self.retry_with_backoff(
                        get_existing_analysis, analysis_id, "get existing analysis"
                    )
                    
                    if existing_analysis:
                        from services.duplicate_persistence_service import DuplicatePersistenceService
                        persistence_service = DuplicatePersistenceService()
                        
                        if not persistence_service.is_analysis_stale(existing_analysis):
                            logger.info(f"Analysis {analysis_id}: Using existing analysis {existing_analysis.analysis_id}")
                            
                            # Update progress to completed
                            self.update_progress(analysis_id, 'completed', 100, 100, 'Using existing analysis results')
                            
                            # Convert existing results to duplicate groups
                            duplicate_groups = persistence_service.convert_to_duplicate_groups(existing_analysis)
                            
                            return {
                                'success': True,
                                'analysis_id': existing_analysis.analysis_id,
                                'duplicate_groups': duplicate_groups,
                                'from_cache': True,
                                'created_at': existing_analysis.created_at,
                                'processing_time': 0.0
                            }
                
                # Phase 1: Load tracks with streaming and memory management
                self.check_cancellation(analysis_id)
                self.check_timeout(analysis_id)
                self.update_progress(analysis_id, 'loading_tracks', 10, 100, 'Loading tracks from database...')
                
                def get_track_query():
                    query = db.session.query(Track)
                    if search_term:
                        search_pattern = f"%{search_term}%"
                        query = query.filter(
                            db.or_(
                                Track.song.ilike(search_pattern),
                                Track.artist.ilike(search_pattern)
                            )
                        )
                    return query
                
                # Get total count for progress tracking
                def get_total_count():
                    return get_track_query().count()
                
                total_tracks = self.retry_with_backoff(get_total_count, analysis_id, "get track count")
                logger.info(f"Analysis {analysis_id}: Found {total_tracks} tracks for analysis")
                
                # Update progress with track count
                self.update_progress(analysis_id, 'analyzing_similarities', 20, 100, 
                                   f'Analyzing similarities for {total_tracks} tracks...')
                
                # Phase 2: Analyze similarities with streaming processing and memory management
                duplicate_groups = []
                processed_tracks = set()
                tracks_processed = 0
                
                # Use streaming processing for large datasets
                if total_tracks > self.streaming_batch_size and self.config.is_streaming_enabled():
                    logger.info(f"Analysis {analysis_id}: Using streaming processing for {total_tracks} tracks")
                    
                    # Process tracks in batches to prevent memory exhaustion
                    track_query = self.retry_with_backoff(get_track_query, analysis_id, "get track query")
                    
                    for batch in self.stream_tracks_in_batches(track_query):
                        self.check_cancellation(analysis_id)
                        self.check_timeout(analysis_id)
                        
                        # Process each track in the batch
                        for i, track1 in enumerate(batch):
                            if track1.id in processed_tracks:
                                continue
                            
                            # Check memory usage periodically
                            if (tracks_processed % self.memory_check_interval == 0 and 
                                self.config.is_memory_monitoring_enabled()):
                                if not self.check_memory_usage(analysis_id):
                                    logger.warning(f"Analysis {analysis_id}: Memory usage still high after cleanup")
                            
                            # Find similar tracks within current batch and remaining tracks
                            similar_tracks = [track1]
                            similarity_scores = {track1.id: 1.0}
                            
                            # Compare with remaining tracks in current batch
                            for j, track2 in enumerate(batch[i+1:], i+1):
                                if track2.id in processed_tracks:
                                    continue
                                
                                similarity = self.get_similarity_score(track1, track2)
                                is_suffix_variation = self.detect_suffix_variations(track1, track2)
                                
                                if similarity >= self.SIMILARITY_THRESHOLD or is_suffix_variation:
                                    similar_tracks.append(track2)
                                    similarity_scores[track2.id] = similarity
                                    processed_tracks.add(track2.id)
                            
                            # Create duplicate group if we found duplicates
                            if len(similar_tracks) > 1:
                                if min_confidence > 0.0:
                                    avg_confidence = sum(similarity_scores.values()) / len(similarity_scores)
                                    if avg_confidence < min_confidence:
                                        for track in similar_tracks:
                                            processed_tracks.add(track.id)
                                        continue
                                
                                canonical = self.suggest_canonical_version(similar_tracks)
                                duplicates = [t for t in similar_tracks if t.id != canonical.id]
                                
                                duplicate_group = DuplicateGroup(
                                    canonical_song=canonical,
                                    duplicates=duplicates,
                                    similarity_scores=similarity_scores,
                                    suggested_action='keep_canonical'
                                )
                                duplicate_groups.append(duplicate_group)
                                
                                for track in similar_tracks:
                                    processed_tracks.add(track.id)
                            else:
                                processed_tracks.add(track1.id)
                            
                            tracks_processed += 1
                            
                            # Save checkpoint every checkpoint_interval tracks
                            if (tracks_processed % self.checkpoint_interval == 0 and 
                                self.config.is_checkpoints_enabled()):
                                self.create_progress_checkpoint(analysis_id, duplicate_groups, tracks_processed, total_tracks)
                            
                            # Force garbage collection periodically
                            if tracks_processed % self.gc_collection_interval == 0:
                                collected = gc.collect()
                                logger.debug(f"Analysis {analysis_id}: Garbage collection freed {collected} objects")
                            
                            # Update progress every 100 tracks
                            if tracks_processed % 100 == 0:
                                percentage = 20 + (tracks_processed / total_tracks) * 60  # 20-80% for analysis
                                memory_usage = self.get_memory_usage()['rss_mb']
                                self.update_progress(analysis_id, 'analyzing_similarities', int(percentage), 100,
                                                   f'Processed {tracks_processed}/{total_tracks} tracks, '
                                                   f'found {len(duplicate_groups)} groups (Memory: {memory_usage:.1f} MB)')
                                
                                logger.info(f"Analysis {analysis_id}: Processed {tracks_processed}/{total_tracks} tracks")
                        
                        # Clean up batch data
                        del batch
                        gc.collect()
                
                else:
                    # For smaller datasets, use traditional approach with memory monitoring
                    def load_all_tracks():
                        return get_track_query().all()
                    
                    all_tracks = self.retry_with_backoff(load_all_tracks, analysis_id, "load all tracks")
                    
                    for i, track1 in enumerate(all_tracks):
                        # Check for cancellation and memory usage
                        self.check_cancellation(analysis_id)
                        self.check_timeout(analysis_id)
                        
                        if (tracks_processed % self.memory_check_interval == 0 and 
                            self.config.is_memory_monitoring_enabled()):
                            self.check_memory_usage(analysis_id)
                        
                        if track1.id in processed_tracks:
                            continue
                        
                        # Find similar tracks
                        similar_tracks = [track1]
                        similarity_scores = {track1.id: 1.0}
                        
                        for j, track2 in enumerate(all_tracks[i+1:], i+1):
                            if track2.id in processed_tracks:
                                continue
                            
                            similarity = self.get_similarity_score(track1, track2)
                            is_suffix_variation = self.detect_suffix_variations(track1, track2)
                            
                            if similarity >= self.SIMILARITY_THRESHOLD or is_suffix_variation:
                                similar_tracks.append(track2)
                                similarity_scores[track2.id] = similarity
                                processed_tracks.add(track2.id)
                        
                        # Create duplicate group if we found duplicates
                        if len(similar_tracks) > 1:
                            if min_confidence > 0.0:
                                avg_confidence = sum(similarity_scores.values()) / len(similarity_scores)
                                if avg_confidence < min_confidence:
                                    for track in similar_tracks:
                                        processed_tracks.add(track.id)
                                    continue
                            
                            canonical = self.suggest_canonical_version(similar_tracks)
                            duplicates = [t for t in similar_tracks if t.id != canonical.id]
                            
                            duplicate_group = DuplicateGroup(
                                canonical_song=canonical,
                                duplicates=duplicates,
                                similarity_scores=similarity_scores,
                                suggested_action='keep_canonical'
                            )
                            duplicate_groups.append(duplicate_group)
                            
                            for track in similar_tracks:
                                processed_tracks.add(track.id)
                        else:
                            processed_tracks.add(track1.id)
                        
                        tracks_processed += 1
                        
                        # Save checkpoint every checkpoint_interval tracks
                        if (tracks_processed % self.checkpoint_interval == 0 and 
                            self.config.is_checkpoints_enabled()):
                            self.create_progress_checkpoint(analysis_id, duplicate_groups, tracks_processed, total_tracks)
                        
                        # Force garbage collection periodically
                        if tracks_processed % self.gc_collection_interval == 0:
                            gc.collect()
                        
                        # Update progress every 100 tracks or at the end
                        if tracks_processed % 100 == 0 or tracks_processed == total_tracks:
                            percentage = 20 + (tracks_processed / total_tracks) * 60  # 20-80% for analysis
                            memory_usage = self.get_memory_usage()['rss_mb']
                            self.update_progress(analysis_id, 'analyzing_similarities', int(percentage), 100,
                                               f'Processed {tracks_processed}/{total_tracks} tracks, '
                                               f'found {len(duplicate_groups)} groups (Memory: {memory_usage:.1f} MB)')
                            
                            logger.info(f"Analysis {analysis_id}: Processed {tracks_processed}/{total_tracks} tracks")
                
                # Phase 3: Sort results
                self.check_cancellation(analysis_id)
                self.check_timeout(analysis_id)
                self.update_progress(analysis_id, 'organizing_results', 85, 100, 'Organizing results...')
                
                # Apply sorting
                if sort_by == 'artist':
                    duplicate_groups.sort(key=lambda g: (g.canonical_song.artist or "").lower())
                elif sort_by == 'song':
                    duplicate_groups.sort(key=lambda g: (g.canonical_song.song or "").lower())
                elif sort_by == 'duplicates':
                    duplicate_groups.sort(key=lambda g: len(g.duplicates), reverse=True)
                elif sort_by == 'confidence':
                    duplicate_groups.sort(key=lambda g: sum(g.similarity_scores.values()) / len(g.similarity_scores), reverse=True)
                
                # Phase 4: Save to persistence if user_id provided
                if user_id:
                    self.check_cancellation(analysis_id)
                    self.check_timeout(analysis_id)
                    self.update_progress(analysis_id, 'saving_results', 90, 100, 'Saving results to database...')
                    
                    def save_analysis():
                        from services.duplicate_persistence_service import DuplicatePersistenceService
                        persistence_service = DuplicatePersistenceService()
                        
                        # Calculate analysis stats
                        analysis_stats = self.get_overall_analysis(duplicate_groups)
                        
                        # Prepare analysis parameters
                        processing_time = (datetime.now() - start_time).total_seconds()
                        analysis_params = {
                            'search_term': search_term,
                            'sort_by': sort_by,
                            'min_confidence': min_confidence,
                            'processing_time': processing_time
                        }
                        
                        # Save to database (persistence service handles transaction safety)
                        return persistence_service.save_analysis_result(
                            user_id, duplicate_groups, analysis_params, analysis_stats
                        )
                    
                    saved_analysis = self.retry_with_backoff(save_analysis, analysis_id, "save analysis results")
                    
                    logger.info(f"Analysis {analysis_id}: Saved results to database as {saved_analysis.analysis_id}")
                    analysis_id = saved_analysis.analysis_id  # Use the saved analysis ID
                
                # Phase 5: Complete
                self.update_progress(analysis_id, 'completed', 100, 100, 
                                   f'Analysis complete! Found {len(duplicate_groups)} duplicate groups')
                
                processing_time = (datetime.now() - start_time).total_seconds()
                logger.info(f"Analysis {analysis_id}: Completed in {processing_time:.2f} seconds, found {len(duplicate_groups)} groups")
                
                # Ensure progress is properly set before returning
                logger.info(f"Analysis {analysis_id}: Progress status set to completed")
                
                return {
                    'success': True,
                    'analysis_id': analysis_id,
                    'duplicate_groups': duplicate_groups,
                    'from_cache': False,
                    'processing_time': processing_time,
                    'total_tracks_analyzed': total_tracks,
                    'groups_found': len(duplicate_groups)
                }
        
        except AnalysisTimeoutError as e:
            # Handle timeout with partial result preservation
            error_message = str(e)
            self.update_progress(analysis_id, 'failed', 0, 100, f'Analysis timed out: {error_message}')
            
            logger.error(f"Analysis {analysis_id}: Timed out: {error_message}")
            
            # Try to preserve partial results
            checkpoint = self.get_analysis_checkpoint(analysis_id)
            partial_groups = checkpoint.get('partial_groups', []) if checkpoint else []
            
            # Update database status if we have user_id
            if user_id:
                try:
                    from services.duplicate_persistence_service import DuplicatePersistenceService
                    persistence_service = DuplicatePersistenceService()
                    persistence_service.update_analysis_status(
                        analysis_id, 'failed', error_message, 
                        {'timeout': True, 'partial_groups_count': len(partial_groups)}
                    )
                except Exception as persist_error:
                    logger.error(f"Failed to update analysis status in database: {persist_error}")
            
            return {
                'success': False,
                'analysis_id': analysis_id,
                'error': error_message,
                'timeout': True,
                'partial_results': len(partial_groups) > 0,
                'partial_groups_count': len(partial_groups),
                'processing_time': (datetime.now() - start_time).total_seconds()
            }
        
        except AnalysisCancelledException as e:
            # Handle cancellation with partial result preservation
            error_message = str(e)
            self.update_progress(analysis_id, 'cancelled', 0, 100, f'Analysis cancelled: {error_message}')
            
            logger.info(f"Analysis {analysis_id}: Cancelled: {error_message}")
            
            # Try to preserve partial results
            checkpoint = self.get_analysis_checkpoint(analysis_id)
            partial_groups = checkpoint.get('partial_groups', []) if checkpoint else []
            
            return {
                'success': False,
                'analysis_id': analysis_id,
                'error': error_message,
                'cancelled': True,
                'partial_results': len(partial_groups) > 0,
                'partial_groups_count': len(partial_groups),
                'processing_time': (datetime.now() - start_time).total_seconds()
            }
        
        except Exception as e:
            # Handle all other errors
            error_message = str(e)
            error_details = {
                'exception_type': type(e).__name__,
                'traceback': traceback.format_exc()
            }
            
            self.update_progress(analysis_id, 'failed', 0, 100, f'Analysis failed: {error_message}')
            
            logger.error(f"Analysis {analysis_id}: Failed with error: {error_message}")
            logger.debug(f"Analysis {analysis_id}: Full traceback: {traceback.format_exc()}")
            
            # Update database status if we have user_id
            if user_id:
                try:
                    from services.duplicate_persistence_service import DuplicatePersistenceService
                    persistence_service = DuplicatePersistenceService()
                    persistence_service.update_analysis_status(analysis_id, 'failed', error_message, error_details)
                except Exception as persist_error:
                    logger.error(f"Failed to update analysis status in database: {persist_error}")
            
            return {
                'success': False,
                'analysis_id': analysis_id,
                'error': error_message,
                'error_details': error_details,
                'processing_time': (datetime.now() - start_time).total_seconds()
            }
        
        finally:
            # Clean up analysis state (but keep progress for frontend detection)
            if analysis_id in self._active_analyses:
                del self._active_analyses[analysis_id]
            
            # Remove from cancelled set if present
            self._cancelled_analyses.discard(analysis_id)
            
            # Note: We intentionally do NOT clean up progress here to allow frontend to detect completion
    
    def get_analysis_progress(self, analysis_id: str) -> Optional[Dict]:
        """
        Get current progress of a running analysis.
        
        Args:
            analysis_id: UUID of the analysis to check
            
        Returns:
            Dictionary with progress information, or None if not found
        """
        with self._progress_lock:
            progress = self._analysis_progress.get(analysis_id)
            
            if not progress:
                return None
            
            return {
                'analysis_id': progress.analysis_id,
                'status': progress.status,
                'phase': progress.phase,
                'current_step': progress.current_step,
                'total_steps': progress.total_steps,
                'percentage': progress.percentage,
                'estimated_remaining_seconds': progress.estimated_remaining_seconds,
                'current_message': progress.current_message,
                'tracks_processed': progress.tracks_processed,
                'total_tracks': progress.total_tracks,
                'groups_found': progress.groups_found,
                'start_time': progress.start_time.isoformat(),
                'last_update': progress.last_update.isoformat(),
                'error_message': progress.error_message
            }
    
    def cancel_analysis(self, analysis_id: str) -> bool:
        """
        Cancel a running analysis gracefully while preserving partial results.
        
        Args:
            analysis_id: UUID of the analysis to cancel
            
        Returns:
            True if analysis was cancelled, False if not found or already completed
        """
        with self._progress_lock:
            progress = self._analysis_progress.get(analysis_id)
            
            if not progress:
                return False
            
            # Only cancel if analysis is still running
            if progress.status in ['starting', 'loading_tracks', 'analyzing_similarities', 'organizing_results', 'saving_results']:
                progress.status = 'cancelled'
                progress.current_message = 'Analysis cancelled by user'
                progress.last_update = datetime.now()
                
                # Log the cancellation
                logger = logging.getLogger(__name__)
                logger.info(f"Analysis {analysis_id}: Cancelled by user request")
                
                return True
            
            return False
    
    def update_progress(self, analysis_id: str, phase: str, current: int, total: int, 
                       message: str, tracks_processed: int = 0, total_tracks: int = 0, 
                       groups_found: int = 0) -> None:
        """
        Update progress information for an analysis with phase tracking, percentage completion, and time estimates.
        
        Args:
            analysis_id: UUID of the analysis
            phase: Current phase of analysis
            current: Current step number
            total: Total number of steps
            message: Current status message
            tracks_processed: Number of tracks processed so far
            total_tracks: Total number of tracks to process
            groups_found: Number of duplicate groups found so far
        """
        with self._progress_lock:
            progress = self._analysis_progress.get(analysis_id)
            
            if not progress:
                return
            
            # Update progress information
            now = datetime.now()
            progress.phase = phase
            progress.current_step = current
            progress.total_steps = total
            progress.percentage = (current / total) * 100 if total > 0 else 0
            progress.current_message = message
            progress.tracks_processed = tracks_processed
            progress.total_tracks = total_tracks
            progress.groups_found = groups_found
            progress.last_update = now
            
            # Calculate estimated remaining time
            if current > 0 and total > current:
                elapsed_seconds = (now - progress.start_time).total_seconds()
                estimated_total_seconds = (elapsed_seconds / current) * total
                progress.estimated_remaining_seconds = int(estimated_total_seconds - elapsed_seconds)
            else:
                progress.estimated_remaining_seconds = None
            
            # Update status based on phase
            if phase == 'completed':
                progress.status = 'completed'
            elif phase == 'failed':
                progress.status = 'failed'
            elif phase == 'cancelled':
                progress.status = 'cancelled'
            else:
                progress.status = phase
        
        # Log progress updates at appropriate intervals
        logger = logging.getLogger(__name__)
        
        # Log every major phase change or every 100 tracks processed
        should_log = (
            phase != getattr(self, '_last_logged_phase', None) or
            (tracks_processed > 0 and tracks_processed % 100 == 0) or
            phase in ['completed', 'failed', 'cancelled']
        )
        
        if should_log:
            if tracks_processed > 0 and total_tracks > 0:
                logger.info(f"Analysis {analysis_id}: {phase} - {message} ({tracks_processed}/{total_tracks} tracks, {groups_found} groups found)")
            else:
                logger.info(f"Analysis {analysis_id}: {phase} - {message}")
            
            self._last_logged_phase = phase
    
    @contextmanager
    def timeout_handler(self, analysis_id: str, timeout_seconds: int = None):
        """
        Context manager for handling analysis timeouts with configurable limits.
        Uses threading-based timeout instead of signals for Flask compatibility.
        
        Args:
            analysis_id: ID of the analysis being performed
            timeout_seconds: Timeout in seconds (uses default if None)
        """
        timeout_seconds = timeout_seconds or self.timeout_seconds
        
        # Store timeout info for the analysis
        timeout_info = {
            'start_time': time.time(),
            'timeout_seconds': timeout_seconds,
            'timed_out': False
        }
        
        # Store timeout info in analysis state
        if analysis_id in self._active_analyses:
            self._active_analyses[analysis_id]['timeout_info'] = timeout_info
        
        try:
            yield
        finally:
            # Clean up timeout info
            if analysis_id in self._active_analyses and 'timeout_info' in self._active_analyses[analysis_id]:
                del self._active_analyses[analysis_id]['timeout_info']
    
    def check_cancellation(self, analysis_id: str):
        """
        Check if analysis has been cancelled and raise exception if so.
        
        Args:
            analysis_id: ID of the analysis to check
            
        Raises:
            AnalysisCancelledException: If analysis has been cancelled
        """
        if analysis_id in self._cancelled_analyses:
            self.logger.info(f"Analysis {analysis_id} was cancelled")
            raise AnalysisCancelledException(f"Analysis {analysis_id} was cancelled")
    
    def check_timeout(self, analysis_id: str):
        """
        Check if analysis has timed out and raise exception if so.
        
        Args:
            analysis_id: ID of the analysis to check
            
        Raises:
            AnalysisTimeoutError: If analysis has timed out
        """
        if analysis_id in self._active_analyses:
            analysis_state = self._active_analyses[analysis_id]
            timeout_info = analysis_state.get('timeout_info')
            
            if timeout_info:
                elapsed_time = time.time() - timeout_info['start_time']
                if elapsed_time > timeout_info['timeout_seconds']:
                    self.logger.warning(f"Analysis {analysis_id} timed out after {elapsed_time:.1f} seconds")
                    raise AnalysisTimeoutError(f"Analysis timed out after {elapsed_time:.1f} seconds")
    
    def cancel_analysis(self, analysis_id: str) -> bool:
        """
        Cancel a running analysis with graceful cancellation and partial result preservation.
        
        Args:
            analysis_id: ID of the analysis to cancel
            
        Returns:
            True if analysis was cancelled, False if not found
        """
        try:
            if analysis_id in self._active_analyses:
                self._cancelled_analyses.add(analysis_id)
                self.logger.info(f"Analysis {analysis_id} marked for cancellation")
                
                # Update analysis status in database
                from services.duplicate_persistence_service import DuplicatePersistenceService
                persistence_service = DuplicatePersistenceService()
                persistence_service.update_analysis_status(analysis_id, 'cancelled')
                
                return True
            return False
            
        except Exception as e:
            self.logger.error(f"Error cancelling analysis {analysis_id}: {str(e)}")
            return False
    
    @contextmanager
    def database_transaction_safety(self, analysis_id: str):
        """
        Context manager for database transaction safety with atomic saves and rollback on failures.
        Note: This is a lightweight wrapper - actual transaction management is handled by the persistence service.
        
        Args:
            analysis_id: ID of the analysis for logging
        """
        try:
            # Don't manage transactions here - let the persistence service handle it
            yield
            self.logger.debug(f"Analysis {analysis_id}: Database operation completed successfully")
            
        except Exception as e:
            self.logger.error(f"Analysis {analysis_id}: Database operation failed: {str(e)}")
            raise
    
    def retry_with_backoff(self, operation, analysis_id: str, operation_name: str, *args, **kwargs):
        """
        Execute operation with retry logic for transient database errors and network issues.
        
        Args:
            operation: Function to execute
            analysis_id: ID of the analysis for logging
            operation_name: Name of the operation for logging
            *args: Arguments to pass to operation
            **kwargs: Keyword arguments to pass to operation
            
        Returns:
            Result of the operation
            
        Raises:
            Exception: If all retry attempts fail
        """
        last_exception = None
        
        for attempt in range(self.max_retry_attempts):
            try:
                self.check_cancellation(analysis_id)
                self.check_timeout(analysis_id)
                result = operation(*args, **kwargs)
                
                if attempt > 0:
                    self.logger.info(f"Analysis {analysis_id}: {operation_name} succeeded on attempt {attempt + 1}")
                
                return result
                
            except (OperationalError, IntegrityError, ConnectionError) as e:
                last_exception = e
                self.logger.warning(
                    f"Analysis {analysis_id}: {operation_name} failed on attempt {attempt + 1}/{self.max_retry_attempts}: {str(e)}"
                )
                
                if attempt < self.max_retry_attempts - 1:
                    # Wait before retrying with exponential backoff
                    delay = self.retry_delay * (2 ** attempt)
                    self.logger.info(f"Analysis {analysis_id}: Retrying {operation_name} in {delay} seconds...")
                    time.sleep(delay)
                else:
                    self.logger.error(f"Analysis {analysis_id}: {operation_name} failed after {self.max_retry_attempts} attempts")
            
            except (AnalysisCancelledException, AnalysisTimeoutError):
                # Don't retry for cancellation or timeout
                raise
            
            except Exception as e:
                # For other exceptions, log and re-raise immediately
                self.logger.error(f"Analysis {analysis_id}: {operation_name} failed with non-retryable error: {str(e)}")
                raise
        
        # If we get here, all retries failed
        raise last_exception
    
    def save_analysis_checkpoint(self, analysis_id: str, partial_groups: List[DuplicateGroup], 
                               processed_count: int, total_count: int):
        """
        Save analysis checkpoint to enable recovery from interruptions.
        
        Args:
            analysis_id: ID of the analysis
            partial_groups: Duplicate groups found so far
            processed_count: Number of tracks processed
            total_count: Total number of tracks to process
        """
        try:
            checkpoint_data = {
                'analysis_id': analysis_id,
                'processed_count': processed_count,
                'total_count': total_count,
                'groups_found': len(partial_groups),
                'timestamp': datetime.now().isoformat(),
                'status': 'checkpoint'
            }
            
            # Store checkpoint in analysis state
            if analysis_id in self._active_analyses:
                self._active_analyses[analysis_id]['checkpoint'] = checkpoint_data
                self._active_analyses[analysis_id]['partial_groups'] = partial_groups
            
            self.logger.debug(f"Analysis {analysis_id}: Checkpoint saved - {processed_count}/{total_count} tracks processed")
            
        except Exception as e:
            self.logger.error(f"Analysis {analysis_id}: Failed to save checkpoint: {str(e)}")
            # Don't raise exception for checkpoint failures
    
    def get_analysis_checkpoint(self, analysis_id: str) -> Optional[Dict]:
        """
        Get the last checkpoint for an analysis to enable resume capability.
        
        Args:
            analysis_id: ID of the analysis
            
        Returns:
            Checkpoint data if available, None otherwise
        """
        try:
            if analysis_id in self._active_analyses:
                return self._active_analyses[analysis_id].get('checkpoint')
            return None
            
        except Exception as e:
            self.logger.error(f"Analysis {analysis_id}: Failed to get checkpoint: {str(e)}")
            return None
    
    def get_memory_usage(self) -> Dict[str, float]:
        """
        Get current memory usage information for resource monitoring.
        
        Returns:
            Dictionary with memory usage statistics in MB
        """
        try:
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            
            return {
                'rss_mb': memory_info.rss / 1024 / 1024,  # Resident Set Size
                'vms_mb': memory_info.vms / 1024 / 1024,  # Virtual Memory Size
                'percent': process.memory_percent(),
                'available_mb': psutil.virtual_memory().available / 1024 / 1024
            }
        except Exception as e:
            self.logger.warning(f"Failed to get memory usage: {str(e)}")
            return {'rss_mb': 0, 'vms_mb': 0, 'percent': 0, 'available_mb': 0}
    
    def check_memory_usage(self, analysis_id: str) -> bool:
        """
        Check if memory usage is within acceptable limits and trigger cleanup if needed.
        
        Args:
            analysis_id: ID of the analysis for logging
            
        Returns:
            True if memory usage is acceptable, False if cleanup was triggered
        """
        try:
            memory_stats = self.get_memory_usage()
            current_usage_mb = memory_stats['rss_mb']
            
            if current_usage_mb > self.max_memory_usage_mb:
                self.logger.warning(
                    f"Analysis {analysis_id}: High memory usage detected ({current_usage_mb:.1f} MB), "
                    f"triggering cleanup"
                )
                
                # Force garbage collection
                self.cleanup_intermediate_results(analysis_id)
                
                # Check memory again after cleanup
                new_memory_stats = self.get_memory_usage()
                new_usage_mb = new_memory_stats['rss_mb']
                
                self.logger.info(
                    f"Analysis {analysis_id}: Memory cleanup reduced usage from "
                    f"{current_usage_mb:.1f} MB to {new_usage_mb:.1f} MB"
                )
                
                return new_usage_mb <= self.max_memory_usage_mb
            
            return True
            
        except Exception as e:
            self.logger.error(f"Analysis {analysis_id}: Failed to check memory usage: {str(e)}")
            return True  # Assume OK if we can't check
    
    def cleanup_intermediate_results(self, analysis_id: str):
        """
        Clean up intermediate results and temporary data to free memory.
        
        Args:
            analysis_id: ID of the analysis for logging
        """
        try:
            # Clear any cached similarity calculations
            if hasattr(self, '_similarity_cache'):
                self._similarity_cache.clear()
            
            # Force garbage collection
            collected = gc.collect()
            self.logger.debug(f"Analysis {analysis_id}: Garbage collection freed {collected} objects")
            
            # Clear analysis state except essential data
            if analysis_id in self._active_analyses:
                state = self._active_analyses[analysis_id]
                # Keep only essential state, clear temporary data
                essential_keys = {'start_time', 'user_id', 'status', 'checkpoint'}
                temp_keys = [k for k in state.keys() if k not in essential_keys]
                for key in temp_keys:
                    if key in state:
                        del state[key]
            
        except Exception as e:
            self.logger.error(f"Analysis {analysis_id}: Failed to cleanup intermediate results: {str(e)}")
    
    def stream_tracks_in_batches(self, query, batch_size: int = None) -> Iterator[List[Track]]:
        """
        Stream tracks from database in batches to prevent memory exhaustion.
        
        Args:
            query: SQLAlchemy query object
            batch_size: Size of each batch (uses default if None)
            
        Yields:
            Lists of Track objects in batches
        """
        batch_size = batch_size or self.streaming_batch_size
        offset = 0
        
        while True:
            batch = query.offset(offset).limit(batch_size).all()
            if not batch:
                break
            
            yield batch
            offset += batch_size
            
            # Force garbage collection after each batch
            gc.collect()
    
    def create_progress_checkpoint(self, analysis_id: str, duplicate_groups: List[DuplicateGroup], 
                                 processed_count: int, total_count: int, 
                                 include_partial_groups: bool = True):
        """
        Create progress checkpoints to enable recovery from interruptions.
        
        Args:
            analysis_id: ID of the analysis
            duplicate_groups: Duplicate groups found so far
            processed_count: Number of tracks processed
            total_count: Total number of tracks to process
            include_partial_groups: Whether to include partial groups in checkpoint
        """
        try:
            checkpoint_data = {
                'analysis_id': analysis_id,
                'processed_count': processed_count,
                'total_count': total_count,
                'groups_found': len(duplicate_groups),
                'timestamp': datetime.now().isoformat(),
                'status': 'checkpoint',
                'memory_usage_mb': self.get_memory_usage()['rss_mb']
            }
            
            # Store checkpoint in analysis state
            if analysis_id in self._active_analyses:
                self._active_analyses[analysis_id]['checkpoint'] = checkpoint_data
                
                # Only store partial groups if requested and memory allows
                if include_partial_groups and self.get_memory_usage()['rss_mb'] < self.max_memory_usage_mb * 0.8:
                    self._active_analyses[analysis_id]['partial_groups'] = duplicate_groups
                else:
                    # Store only essential group metadata to save memory
                    group_metadata = [
                        {
                            'canonical_id': group.canonical_song.id,
                            'duplicate_count': len(group.duplicates),
                            'avg_similarity': sum(group.similarity_scores.values()) / len(group.similarity_scores)
                        }
                        for group in duplicate_groups
                    ]
                    self._active_analyses[analysis_id]['group_metadata'] = group_metadata
            
            self.logger.debug(
                f"Analysis {analysis_id}: Progress checkpoint created - "
                f"{processed_count}/{total_count} tracks processed, "
                f"{len(duplicate_groups)} groups found"
            )
            
        except Exception as e:
            self.logger.error(f"Analysis {analysis_id}: Failed to create progress checkpoint: {str(e)}")
    
    @contextmanager
    def request_timeout_handler(self, analysis_id: str, operation_name: str, 
                              timeout_seconds: int = None):
        """
        Context manager for handling individual request timeouts and resource usage monitoring.
        Uses threading-based timeout instead of signals for Flask compatibility.
        
        Args:
            analysis_id: ID of the analysis
            operation_name: Name of the operation for logging
            timeout_seconds: Timeout in seconds (uses default if None)
        """
        timeout_seconds = timeout_seconds or self.request_timeout_seconds
        start_time = time.time()
        
        try:
            yield
            
            # Check if operation exceeded timeout after completion
            elapsed_time = time.time() - start_time
            if elapsed_time > timeout_seconds:
                self.logger.warning(
                    f"Analysis {analysis_id}: {operation_name} took {elapsed_time:.1f}s "
                    f"(exceeded timeout of {timeout_seconds}s)"
                )
        except Exception as e:
            elapsed_time = time.time() - start_time
            if elapsed_time > timeout_seconds:
                self.logger.warning(
                    f"Analysis {analysis_id}: {operation_name} timed out after {elapsed_time:.1f} seconds"
                )
                raise AnalysisTimeoutError(f"{operation_name} timed out after {elapsed_time:.1f} seconds")
            raise

    def cleanup_completed_progress(self, max_age_hours: int = 24) -> int:
        """
        Clean up progress information for completed analyses to prevent memory leaks.
        Keep completed analyses for at least 5 minutes to allow frontend to detect completion.
        
        Args:
            max_age_hours: Maximum age in hours for keeping completed progress info
            
        Returns:
            Number of progress records cleaned up
        """
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        # Keep completed analyses for at least 5 minutes
        min_completion_time = datetime.now() - timedelta(minutes=5)
        cleaned_count = 0
        
        with self._progress_lock:
            # Find analyses to clean up
            to_remove = []
            for analysis_id, progress in self._analysis_progress.items():
                if (progress.status in ['completed', 'failed', 'cancelled'] and 
                    progress.last_update < cutoff_time and
                    progress.last_update < min_completion_time):
                    to_remove.append(analysis_id)
            
            # Remove them
            for analysis_id in to_remove:
                del self._analysis_progress[analysis_id]
                cleaned_count += 1
        
        if cleaned_count > 0:
            logger = logging.getLogger(__name__)
            logger.info(f"Cleaned up {cleaned_count} completed analysis progress records")
        
        return cleaned_count