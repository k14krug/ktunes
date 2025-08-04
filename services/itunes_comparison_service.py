"""
iTunes Comparison Service for cross-referencing duplicate songs with iTunes XML catalog.

This service extends the existing iTunes functionality to provide comparison
capabilities for duplicate detection and management.
"""

import os
import logging
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime
from models import Track
from services.itunes_service import ITunesXMLParser
from services.duplicate_detection_service import DuplicateGroup
import difflib


@dataclass
class ITunesTrack:
    """Data transfer object for iTunes track information."""
    name: str
    artist: str
    album: Optional[str]
    location: Optional[str]
    play_count: Optional[int]
    last_played: Optional[datetime]
    date_added: Optional[datetime]
    genre: Optional[str]


@dataclass
class ITunesMatch:
    """Data transfer object for iTunes match results."""
    found: bool
    itunes_track: Optional[ITunesTrack]
    confidence_score: float
    metadata_differences: List[str]
    match_type: str  # 'exact', 'fuzzy', 'none'


@dataclass
class MetadataComparison:
    """Data transfer object for metadata comparison results."""
    differences: List[str]
    similarities: List[str]
    confidence_score: float
    recommendation: str


class ITunesComparisonService:
    """Service for comparing duplicate songs with iTunes XML catalog."""
    
    def __init__(self, xml_path: Optional[str] = None):
        """
        Initialize the iTunes comparison service.
        
        Args:
            xml_path: Path to iTunes XML file. If None, will try to get from config.
        """
        self.xml_path = xml_path
        self.library = None
        self.itunes_tracks_cache = {}
        self.initialization_error = None
        self._initialize_library()
    
    def _initialize_library(self):
        """Initialize the iTunes library with comprehensive error handling."""
        from services.error_handling_service import get_error_service
        error_service = get_error_service()
        
        if not self.xml_path:
            # Try to get from application config
            try:
                from config_loader import load_config
                config = load_config()
                self.xml_path = os.path.join(config.get('itunes_dir', ''), config.get('itunes_lib', ''))
            except Exception as e:
                logging.warning(f"Could not load iTunes config: {e}")
                return
        
        if not self.xml_path:
            logging.warning("No iTunes XML path configured")
            return
        
        try:
            # Check if file exists and is accessible
            if not os.path.exists(self.xml_path):
                raise FileNotFoundError(f"iTunes XML file not found: {self.xml_path}")
            
            if not os.access(self.xml_path, os.R_OK):
                raise PermissionError(f"Cannot read iTunes XML file: {self.xml_path}")
            
            # Check file size (empty files are problematic)
            file_size = os.path.getsize(self.xml_path)
            if file_size == 0:
                raise ValueError(f"iTunes XML file is empty: {self.xml_path}")
            
            # Try to parse the iTunes library
            parser = ITunesXMLParser(self.xml_path)
            self.library = parser.library
            
            if not self.library:
                raise ValueError("iTunes library parser returned empty library")
            
            # Build tracks cache
            self._build_tracks_cache()
            
            logging.info(f"iTunes library loaded successfully with {len(self.itunes_tracks_cache)} tracks")
            
        except Exception as e:
            # Handle iTunes XML access errors comprehensively
            error_details = error_service.handle_itunes_xml_error(self.xml_path, e)
            
            # Log the detailed error
            logging.error(f"iTunes library initialization failed: {error_details['error_message']}")
            for suggestion in error_details.get('suggestions', []):
                logging.info(f"Suggestion: {suggestion}")
            
            # Store error details for later retrieval
            self.initialization_error = error_details
            self.library = None
    
    def _build_tracks_cache(self):
        """Build a cache of iTunes tracks for faster lookup."""
        if not self.library:
            return
        
        self.itunes_tracks_cache = {}
        
        for song in self.library.songs.values():
            if song.name and song.artist:
                # Create normalized keys for lookup
                key_exact = (song.name.lower().strip(), song.artist.lower().strip())
                
                itunes_track = ITunesTrack(
                    name=song.name,
                    artist=song.artist,
                    album=song.album,
                    location=song.location,
                    play_count=song.play_count,
                    last_played=self._parse_itunes_date(song.lastplayed),
                    date_added=self._parse_itunes_date(song.date_added),
                    genre=song.genre
                )
                
                # Store with exact key
                self.itunes_tracks_cache[key_exact] = itunes_track
    
    def _parse_itunes_date(self, date_value) -> Optional[datetime]:
        """Parse iTunes date value to datetime object."""
        if not date_value:
            return None
        
        try:
            # Reuse the parsing logic from ITunesXMLParser
            parser = ITunesXMLParser(self.xml_path)
            return parser._parse_date(date_value)
        except Exception as e:
            logging.warning(f"Error parsing iTunes date: {e}")
            return None
    
    def is_available(self) -> bool:
        """Check if iTunes library is available for comparison."""
        return self.library is not None and len(self.itunes_tracks_cache) > 0
    
    def get_initialization_error(self) -> Optional[Dict[str, Any]]:
        """Get details about iTunes library initialization error, if any."""
        return self.initialization_error
    
    def find_itunes_matches(self, duplicate_group: DuplicateGroup) -> Dict[int, ITunesMatch]:
        """
        Find iTunes matches for all songs in a duplicate group.
        
        Args:
            duplicate_group: The duplicate group to find matches for
            
        Returns:
            Dictionary mapping track IDs to iTunes match results
        """
        if not self.is_available():
            return {}
        
        matches = {}
        all_songs = [duplicate_group.canonical_song] + duplicate_group.duplicates
        
        for song in all_songs:
            match = self.find_itunes_match(song)
            matches[song.id] = match
        
        return matches
    
    def find_itunes_match(self, track: Track) -> ITunesMatch:
        """
        Find iTunes match for a single track.
        
        Args:
            track: The track to find a match for
            
        Returns:
            ITunesMatch object with match results
        """
        if not self.is_available() or not track.song or not track.artist:
            return ITunesMatch(
                found=False,
                itunes_track=None,
                confidence_score=0.0,
                metadata_differences=[],
                match_type='none'
            )
        
        # Try exact match first
        exact_key = (track.song.lower().strip(), track.artist.lower().strip())
        if exact_key in self.itunes_tracks_cache:
            itunes_track = self.itunes_tracks_cache[exact_key]
            return ITunesMatch(
                found=True,
                itunes_track=itunes_track,
                confidence_score=1.0,
                metadata_differences=self._get_metadata_differences(track, itunes_track),
                match_type='exact'
            )
        
        # Try fuzzy matching
        best_match = self._find_fuzzy_match(track)
        if best_match:
            return best_match
        
        # No match found
        return ITunesMatch(
            found=False,
            itunes_track=None,
            confidence_score=0.0,
            metadata_differences=[],
            match_type='none'
        )
    
    def _find_fuzzy_match(self, track: Track) -> Optional[ITunesMatch]:
        """
        Find fuzzy match for a track using similarity algorithms.
        
        Args:
            track: The track to find a match for
            
        Returns:
            ITunesMatch object if a good fuzzy match is found, None otherwise
        """
        if not track.song or not track.artist:
            return None
        
        track_song = track.song.lower().strip()
        track_artist = track.artist.lower().strip()
        
        best_score = 0.0
        best_match = None
        
        # Search through iTunes tracks for fuzzy matches
        for (itunes_song, itunes_artist), itunes_track in self.itunes_tracks_cache.items():
            # Calculate similarity scores
            song_similarity = difflib.SequenceMatcher(None, track_song, itunes_song).ratio()
            artist_similarity = difflib.SequenceMatcher(None, track_artist, itunes_artist).ratio()
            
            # Combined score (weight song title more heavily)
            combined_score = (song_similarity * 0.7) + (artist_similarity * 0.3)
            
            if combined_score > best_score and combined_score > 0.8:  # Minimum threshold
                best_score = combined_score
                best_match = itunes_track
        
        if best_match and best_score > 0.8:
            return ITunesMatch(
                found=True,
                itunes_track=best_match,
                confidence_score=best_score,
                metadata_differences=self._get_metadata_differences(track, best_match),
                match_type='fuzzy'
            )
        
        return None
    
    def get_itunes_metadata(self, song_name: str, artist_name: str) -> Optional[ITunesTrack]:
        """
        Get iTunes metadata for a specific song and artist.
        
        Args:
            song_name: Name of the song
            artist_name: Name of the artist
            
        Returns:
            ITunesTrack object if found, None otherwise
        """
        if not self.is_available():
            return None
        
        key = (song_name.lower().strip(), artist_name.lower().strip())
        return self.itunes_tracks_cache.get(key)
    
    def compare_metadata(self, db_track: Track, itunes_track: ITunesTrack) -> MetadataComparison:
        """
        Compare metadata between database track and iTunes track.
        
        Args:
            db_track: Track from database
            itunes_track: Track from iTunes
            
        Returns:
            MetadataComparison object with detailed comparison
        """
        differences = []
        similarities = []
        warnings = []
        
        try:
            # Compare basic metadata with null safety
            db_song = db_track.song or ""
            itunes_song = itunes_track.name or ""
            if db_song.strip() != itunes_song.strip():
                differences.append(f"Song title: '{db_song}' vs '{itunes_song}'")
            else:
                similarities.append("Song title matches")
            
            db_artist = db_track.artist or ""
            itunes_artist = itunes_track.artist or ""
            if db_artist.strip() != itunes_artist.strip():
                differences.append(f"Artist: '{db_artist}' vs '{itunes_artist}'")
            else:
                similarities.append("Artist matches")
            
            db_album = db_track.album or ""
            itunes_album = itunes_track.album or ""
            if db_album.strip() != itunes_album.strip():
                differences.append(f"Album: '{db_album}' vs '{itunes_album}'")
            else:
                similarities.append("Album matches")
            
            # Compare play counts with detailed analysis
            db_plays = db_track.play_cnt or 0
            itunes_plays = itunes_track.play_count or 0
            if db_plays != itunes_plays:
                play_diff = abs(db_plays - itunes_plays)
                if play_diff > max(db_plays, itunes_plays) * 0.5:  # Significant difference
                    warnings.append(f"Large play count difference: {db_plays} vs {itunes_plays}")
                differences.append(f"Play count: {db_plays} vs {itunes_plays}")
            else:
                similarities.append("Play count matches")
            
            # Compare dates with tolerance
            if db_track.last_play_dt and itunes_track.last_played:
                try:
                    db_date = db_track.last_play_dt.date()
                    itunes_date = itunes_track.last_played.date()
                    date_diff = abs((db_date - itunes_date).days)
                    
                    if date_diff == 0:
                        similarities.append("Last played date matches exactly")
                    elif date_diff <= 1:
                        similarities.append("Last played date matches (within 1 day)")
                    elif date_diff <= 7:
                        differences.append(f"Last played: {db_date} vs {itunes_date} (within 1 week)")
                    else:
                        differences.append(f"Last played: {db_date} vs {itunes_date} ({date_diff} days apart)")
                except Exception as e:
                    warnings.append(f"Error comparing last played dates: {e}")
            elif db_track.last_play_dt and not itunes_track.last_played:
                differences.append("Database has last played date, iTunes does not")
            elif not db_track.last_play_dt and itunes_track.last_played:
                differences.append("iTunes has last played date, database does not")
            else:
                similarities.append("Both missing last played date")
            
            if db_track.date_added and itunes_track.date_added:
                try:
                    db_added = db_track.date_added.date()
                    itunes_added = itunes_track.date_added.date()
                    added_diff = abs((db_added - itunes_added).days)
                    
                    if added_diff == 0:
                        similarities.append("Date added matches exactly")
                    elif added_diff <= 1:
                        similarities.append("Date added matches (within 1 day)")
                    else:
                        differences.append(f"Date added: {db_added} vs {itunes_added} ({added_diff} days apart)")
                except Exception as e:
                    warnings.append(f"Error comparing date added: {e}")
            elif db_track.date_added and not itunes_track.date_added:
                differences.append("Database has date added, iTunes does not")
            elif not db_track.date_added and itunes_track.date_added:
                differences.append("iTunes has date added, database does not")
            else:
                similarities.append("Both missing date added")
            
            # Compare file location if available
            if hasattr(db_track, 'location') and db_track.location and itunes_track.location:
                if db_track.location != itunes_track.location:
                    differences.append(f"File location: '{db_track.location}' vs '{itunes_track.location}'")
                else:
                    similarities.append("File location matches")
            
            # Add genre information if available
            if itunes_track.genre:
                if hasattr(db_track, 'category') and db_track.category:
                    if db_track.category.lower() != itunes_track.genre.lower():
                        differences.append(f"Category/Genre: '{db_track.category}' vs '{itunes_track.genre}'")
                    else:
                        similarities.append("Category/Genre matches")
                else:
                    differences.append(f"iTunes has genre '{itunes_track.genre}', database category not set")
            
        except Exception as e:
            warnings.append(f"Error during metadata comparison: {e}")
            logging.error(f"Error comparing metadata for {db_track.song}: {e}")
        
        # Calculate confidence score with weighted factors
        total_comparisons = len(differences) + len(similarities)
        if total_comparisons == 0:
            confidence_score = 0.0
        else:
            base_confidence = len(similarities) / total_comparisons
            
            # Reduce confidence for warnings
            warning_penalty = len(warnings) * 0.1
            confidence_score = max(0.0, base_confidence - warning_penalty)
        
        # Generate recommendation with warnings consideration
        if warnings:
            if confidence_score > 0.7:
                recommendation = "Good match with some concerns - review warnings"
            elif confidence_score > 0.5:
                recommendation = "Moderate match with concerns - manual review recommended"
            else:
                recommendation = "Low confidence match with significant concerns"
        else:
            if confidence_score > 0.8:
                recommendation = "High confidence match - metadata is very similar"
            elif confidence_score > 0.6:
                recommendation = "Good match - some metadata differences exist"
            elif confidence_score > 0.4:
                recommendation = "Moderate match - significant metadata differences"
            else:
                recommendation = "Low confidence match - many metadata differences"
        
        # Combine differences and warnings for comprehensive feedback
        all_differences = differences + [f"WARNING: {w}" for w in warnings]
        
        return MetadataComparison(
            differences=all_differences,
            similarities=similarities,
            confidence_score=confidence_score,
            recommendation=recommendation
        )
    
    def _get_metadata_differences(self, db_track: Track, itunes_track: ITunesTrack) -> List[str]:
        """
        Get a list of metadata differences between database and iTunes track.
        
        Args:
            db_track: Track from database
            itunes_track: Track from iTunes
            
        Returns:
            List of difference descriptions
        """
        comparison = self.compare_metadata(db_track, itunes_track)
        return comparison.differences
    
    def get_itunes_statistics(self) -> Dict[str, any]:
        """
        Get statistics about the iTunes library.
        
        Returns:
            Dictionary with iTunes library statistics
        """
        if not self.is_available():
            return {
                'available': False,
                'total_tracks': 0,
                'error': 'iTunes library not available'
            }
        
        # Calculate some basic statistics
        total_tracks = len(self.itunes_tracks_cache)
        tracks_with_play_count = sum(1 for track in self.itunes_tracks_cache.values() if track.play_count and track.play_count > 0)
        tracks_with_last_played = sum(1 for track in self.itunes_tracks_cache.values() if track.last_played)
        
        # Get genre distribution
        genres = {}
        for track in self.itunes_tracks_cache.values():
            if track.genre:
                genres[track.genre] = genres.get(track.genre, 0) + 1
        
        return {
            'available': True,
            'total_tracks': total_tracks,
            'tracks_with_play_count': tracks_with_play_count,
            'tracks_with_last_played': tracks_with_last_played,
            'unique_genres': len(genres),
            'top_genres': sorted(genres.items(), key=lambda x: x[1], reverse=True)[:10],
            'xml_path': self.xml_path
        }
    
    def validate_itunes_connection(self) -> Dict[str, any]:
        """
        Validate the iTunes library connection and provide diagnostic information.
        
        Returns:
            Dictionary with validation results and diagnostic info
        """
        validation_result = {
            'valid': False,
            'errors': [],
            'warnings': [],
            'info': []
        }
        
        try:
            # Check if XML path exists
            if not self.xml_path:
                validation_result['errors'].append("No iTunes XML path configured")
                return validation_result
            
            if not os.path.exists(self.xml_path):
                validation_result['errors'].append(f"iTunes XML file not found: {self.xml_path}")
                return validation_result
            
            validation_result['info'].append(f"iTunes XML file found: {self.xml_path}")
            
            # Check if library is loaded
            if not self.library:
                validation_result['errors'].append("iTunes library failed to load")
                return validation_result
            
            validation_result['info'].append("iTunes library loaded successfully")
            
            # Check cache
            if not self.itunes_tracks_cache:
                validation_result['warnings'].append("iTunes tracks cache is empty")
            else:
                validation_result['info'].append(f"iTunes cache contains {len(self.itunes_tracks_cache)} tracks")
            
            # Check for common issues
            tracks_without_names = sum(1 for track in self.itunes_tracks_cache.values() if not track.name)
            if tracks_without_names > 0:
                validation_result['warnings'].append(f"{tracks_without_names} tracks missing song names")
            
            tracks_without_artists = sum(1 for track in self.itunes_tracks_cache.values() if not track.artist)
            if tracks_without_artists > 0:
                validation_result['warnings'].append(f"{tracks_without_artists} tracks missing artist names")
            
            # File modification time check
            try:
                import os.path
                mod_time = os.path.getmtime(self.xml_path)
                mod_datetime = datetime.fromtimestamp(mod_time)
                days_old = (datetime.now() - mod_datetime).days
                
                if days_old > 30:
                    validation_result['warnings'].append(f"iTunes XML file is {days_old} days old")
                else:
                    validation_result['info'].append(f"iTunes XML file is {days_old} days old")
                    
            except Exception as e:
                validation_result['warnings'].append(f"Could not check XML file age: {e}")
            
            validation_result['valid'] = len(validation_result['errors']) == 0
            
        except Exception as e:
            validation_result['errors'].append(f"Validation error: {e}")
            logging.error(f"iTunes validation error: {e}")
        
        return validation_result
    
    def get_match_confidence_factors(self, db_track: Track, itunes_match: ITunesMatch) -> Dict[str, any]:
        """
        Get detailed confidence factors for an iTunes match.
        
        Args:
            db_track: Database track
            itunes_match: iTunes match result
            
        Returns:
            Dictionary with detailed confidence analysis
        """
        if not itunes_match.found or not itunes_match.itunes_track:
            return {
                'overall_confidence': 0.0,
                'factors': [],
                'concerns': ['No iTunes match found'],
                'recommendation': 'No match available'
            }
        
        factors = []
        concerns = []
        confidence_components = {}
        
        try:
            # Match type factor
            if itunes_match.match_type == 'exact':
                factors.append("Exact title and artist match")
                confidence_components['match_type'] = 1.0
            elif itunes_match.match_type == 'fuzzy':
                factors.append(f"Fuzzy match (similarity: {itunes_match.confidence_score:.2f})")
                confidence_components['match_type'] = itunes_match.confidence_score
            else:
                concerns.append("Unknown match type")
                confidence_components['match_type'] = 0.0
            
            # Metadata comparison
            metadata_comparison = self.compare_metadata(db_track, itunes_match.itunes_track)
            confidence_components['metadata'] = metadata_comparison.confidence_score
            
            if metadata_comparison.confidence_score > 0.8:
                factors.append("High metadata similarity")
            elif metadata_comparison.confidence_score > 0.6:
                factors.append("Good metadata similarity")
            else:
                concerns.append("Low metadata similarity")
            
            # Play count analysis
            db_plays = db_track.play_cnt or 0
            itunes_plays = itunes_match.itunes_track.play_count or 0
            
            if db_plays == itunes_plays:
                factors.append("Play counts match exactly")
                confidence_components['play_count'] = 1.0
            elif abs(db_plays - itunes_plays) <= max(db_plays, itunes_plays) * 0.1:
                factors.append("Play counts very similar")
                confidence_components['play_count'] = 0.9
            elif abs(db_plays - itunes_plays) <= max(db_plays, itunes_plays) * 0.3:
                factors.append("Play counts moderately similar")
                confidence_components['play_count'] = 0.7
            else:
                concerns.append(f"Play counts differ significantly: {db_plays} vs {itunes_plays}")
                confidence_components['play_count'] = 0.3
            
            # Date analysis
            date_score = 0.0
            date_factors = 0
            
            if db_track.last_play_dt and itunes_match.itunes_track.last_played:
                date_diff = abs((db_track.last_play_dt.date() - itunes_match.itunes_track.last_played.date()).days)
                if date_diff == 0:
                    factors.append("Last played dates match")
                    date_score += 1.0
                elif date_diff <= 7:
                    factors.append("Last played dates close")
                    date_score += 0.8
                else:
                    concerns.append(f"Last played dates differ by {date_diff} days")
                    date_score += 0.3
                date_factors += 1
            
            if db_track.date_added and itunes_match.itunes_track.date_added:
                added_diff = abs((db_track.date_added.date() - itunes_match.itunes_track.date_added.date()).days)
                if added_diff <= 1:
                    factors.append("Date added matches")
                    date_score += 1.0
                else:
                    concerns.append(f"Date added differs by {added_diff} days")
                    date_score += 0.5
                date_factors += 1
            
            confidence_components['dates'] = date_score / date_factors if date_factors > 0 else 0.5
            
            # Calculate overall confidence
            weights = {
                'match_type': 0.4,
                'metadata': 0.3,
                'play_count': 0.2,
                'dates': 0.1
            }
            
            overall_confidence = sum(
                confidence_components.get(component, 0.0) * weight
                for component, weight in weights.items()
            )
            
            # Generate recommendation
            if overall_confidence > 0.9:
                recommendation = "Very high confidence - excellent match"
            elif overall_confidence > 0.8:
                recommendation = "High confidence - good match"
            elif overall_confidence > 0.6:
                recommendation = "Moderate confidence - review recommended"
            elif overall_confidence > 0.4:
                recommendation = "Low confidence - manual verification needed"
            else:
                recommendation = "Very low confidence - likely not the same track"
            
        except Exception as e:
            concerns.append(f"Error analyzing confidence: {e}")
            overall_confidence = 0.0
            recommendation = "Error in confidence analysis"
            logging.error(f"Error in confidence analysis: {e}")
        
        return {
            'overall_confidence': overall_confidence,
            'confidence_components': confidence_components,
            'factors': factors,
            'concerns': concerns,
            'recommendation': recommendation
        }