"""
Duplicate Persistence Service for managing duplicate analysis results.

This service provides functionality to save, load, and manage duplicate detection
results in the database, allowing users to return to their analysis work later.
"""

import uuid
import json
import csv
import tempfile
import os
import logging
import traceback
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, IO
from contextlib import contextmanager
from sqlalchemy import desc, and_, func
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError, OperationalError, IntegrityError

from extensions import db
from models import (
    DuplicateAnalysisResult, 
    DuplicateAnalysisGroup, 
    DuplicateAnalysisTrack,
    DuplicateAnalysisExport,
    Track,
    User,
    UserPreferences
)
from services.duplicate_detection_service import DuplicateGroup, DuplicateAnalysis


class DuplicatePersistenceService:
    """Service for managing persistent storage of duplicate analysis results."""
    
    def __init__(self):
        """Initialize the duplicate persistence service."""
        self.cleanup_days = 30
        self.max_results_per_user = 5
        self.logger = logging.getLogger(__name__)
        
        # Error handling configuration
        self.max_retry_attempts = 3
        self.retry_delay_seconds = 2
    
    def save_analysis_result(self, user_id: int, duplicate_groups: List[DuplicateGroup], 
                           analysis_params: Dict, analysis_stats: DuplicateAnalysis) -> DuplicateAnalysisResult:
        """
        Store complete analysis results in normalized database structure with comprehensive error handling.
        
        Args:
            user_id: ID of the user who performed the analysis
            duplicate_groups: List of duplicate groups found
            analysis_params: Parameters used for the analysis (search_term, sort_by, min_confidence)
            analysis_stats: Overall analysis statistics
            
        Returns:
            DuplicateAnalysisResult: The saved analysis result record
        """
        def _save_analysis():
            with self.database_transaction_safety("save analysis result"):
                # Generate unique analysis ID
                analysis_id = str(uuid.uuid4())
                
                # Get current library statistics with retry
                def get_library_stats():
                    total_tracks = db.session.query(Track).count()
                    library_last_modified = db.session.query(func.max(Track.date_added)).scalar()
                    return total_tracks, library_last_modified
                
                total_tracks, library_last_modified = self.retry_with_backoff(
                    get_library_stats, "get library statistics"
                )
                
                # Create main analysis result record
                analysis_result = DuplicateAnalysisResult(
                    analysis_id=analysis_id,
                    user_id=user_id,
                    created_at=datetime.now(),
                    completed_at=datetime.now(),
                    status='completed',
                    
                    # Analysis parameters
                    search_term=analysis_params.get('search_term'),
                    sort_by=analysis_params.get('sort_by', 'artist'),
                    min_confidence=analysis_params.get('min_confidence', 0.0),
                    
                    # Analysis results summary
                    total_tracks_analyzed=total_tracks,
                    total_groups_found=analysis_stats.total_groups,
                    total_duplicates_found=analysis_stats.total_duplicates,
                    average_similarity_score=analysis_stats.average_similarity_score,
                    processing_time_seconds=analysis_params.get('processing_time', 0.0),
                    
                    # Library state tracking
                    library_track_count=total_tracks,
                    library_last_modified=library_last_modified
                )
                
                db.session.add(analysis_result)
                db.session.flush()  # Get the ID without committing
                
                # Save duplicate groups in batches to manage memory usage
                batch_size = 50  # Process groups in batches
                total_groups = len(duplicate_groups)
                
                for batch_start in range(0, total_groups, batch_size):
                    batch_end = min(batch_start + batch_size, total_groups)
                    group_batch = duplicate_groups[batch_start:batch_end]
                    
                    # Process each group in the batch
                    for group_index, group in enumerate(group_batch, batch_start):
                        # Create group record
                        analysis_group = DuplicateAnalysisGroup(
                            analysis_id=analysis_id,
                            group_index=group_index,
                            canonical_track_id=group.canonical_song.id,
                            duplicate_count=len(group.duplicates),
                            average_similarity_score=sum(group.similarity_scores.values()) / len(group.similarity_scores),
                            suggested_action=group.suggested_action,
                            has_itunes_matches=False,  # Will be updated when iTunes integration is added
                            itunes_match_data=None
                        )
                        
                        db.session.add(analysis_group)
                        db.session.flush()  # Get the group ID
                        
                        # Save all tracks in the group (canonical + duplicates)
                        all_tracks = [group.canonical_song] + group.duplicates
                        
                        for track in all_tracks:
                            analysis_track = DuplicateAnalysisTrack(
                                group_id=analysis_group.id,
                                track_id=track.id,
                                
                                # Track snapshot
                                song_name=track.song,
                                artist_name=track.artist,
                                album_name=track.album,
                                play_count=track.play_cnt,
                                last_played=track.last_play_dt,
                                date_added=track.date_added,
                                
                                # Analysis metadata
                                similarity_score=group.similarity_scores.get(track.id, 1.0),
                                is_canonical=(track.id == group.canonical_song.id),
                                
                                # iTunes integration (placeholder)
                                itunes_match_found=False,
                                itunes_match_confidence=None,
                                itunes_match_type=None
                            )
                            
                            db.session.add(analysis_track)
                    
                    # Flush batch to database and clear session cache
                    db.session.flush()
                    
                    # Force garbage collection after each batch
                    import gc
                    gc.collect()
                    
                    self.logger.debug(f"Saved batch {batch_start}-{batch_end} of {total_groups} groups")
                
                return analysis_result
        
        try:
            return self.retry_with_backoff(_save_analysis, "save analysis result")
            
        except Exception as e:
            error_details = {
                'exception_type': type(e).__name__,
                'traceback': traceback.format_exc(),
                'user_id': user_id,
                'groups_count': len(duplicate_groups),
                'analysis_params': analysis_params
            }
            
            self.logger.error(f"Failed to save analysis result: {str(e)}")
            self.logger.debug(f"Save analysis error details: {error_details}")
            
            raise Exception(f"Failed to save analysis result: {str(e)}")
    
    def load_analysis_result(self, analysis_id: str) -> Optional[DuplicateAnalysisResult]:
        """
        Retrieve analysis results with all related data.
        
        Args:
            analysis_id: UUID of the analysis to load
            
        Returns:
            DuplicateAnalysisResult with loaded groups and tracks, or None if not found
        """
        try:
            # Load analysis with all related data using eager loading
            analysis_result = db.session.query(DuplicateAnalysisResult)\
                .options(
                    joinedload(DuplicateAnalysisResult.groups)
                    .joinedload(DuplicateAnalysisGroup.tracks)
                )\
                .filter(DuplicateAnalysisResult.analysis_id == analysis_id)\
                .first()
            
            return analysis_result
            
        except Exception as e:
            raise Exception(f"Failed to load analysis result: {str(e)}")
    
    def get_latest_analysis(self, user_id: int, search_term: Optional[str] = None) -> Optional[DuplicateAnalysisResult]:
        """
        Find most recent analysis for user with optional search filtering.
        
        Args:
            user_id: ID of the user
            search_term: Optional search term to match against saved analyses
            
        Returns:
            Most recent DuplicateAnalysisResult matching criteria, or None
        """
        try:
            query = db.session.query(DuplicateAnalysisResult)\
                .filter(DuplicateAnalysisResult.user_id == user_id)\
                .filter(DuplicateAnalysisResult.status == 'completed')
            
            # Filter by search term if provided
            if search_term:
                query = query.filter(DuplicateAnalysisResult.search_term == search_term)
            
            # Get the most recent analysis
            latest_analysis = query.order_by(desc(DuplicateAnalysisResult.created_at)).first()
            
            return latest_analysis
            
        except Exception as e:
            raise Exception(f"Failed to get latest analysis: {str(e)}")
    
    def get_user_analyses(self, user_id: int, limit: int = 10, offset: int = 0) -> List[DuplicateAnalysisResult]:
        """
        List analysis history with pagination support.
        
        Args:
            user_id: ID of the user
            limit: Maximum number of results to return
            offset: Number of results to skip (for pagination)
            
        Returns:
            List of DuplicateAnalysisResult objects ordered by creation date (newest first)
        """
        try:
            analyses = db.session.query(DuplicateAnalysisResult)\
                .filter(DuplicateAnalysisResult.user_id == user_id)\
                .order_by(desc(DuplicateAnalysisResult.created_at))\
                .limit(limit)\
                .offset(offset)\
                .all()
            
            return analyses
            
        except Exception as e:
            raise Exception(f"Failed to get user analyses: {str(e)}")
    
    def get_user_analyses_count(self, user_id: int) -> int:
        """
        Get total count of analyses for a user (for pagination).
        
        Args:
            user_id: ID of the user
            
        Returns:
            Total number of analyses for the user
        """
        try:
            count = db.session.query(DuplicateAnalysisResult)\
                .filter(DuplicateAnalysisResult.user_id == user_id)\
                .count()
            
            return count
            
        except Exception as e:
            raise Exception(f"Failed to get user analyses count: {str(e)}")
    
    def convert_to_duplicate_groups(self, analysis_result: DuplicateAnalysisResult) -> List[DuplicateGroup]:
        """
        Convert saved analysis result back to DuplicateGroup objects for display.
        
        Args:
            analysis_result: The saved analysis result
            
        Returns:
            List of DuplicateGroup objects reconstructed from saved data
        """
        try:
            duplicate_groups = []
            
            for group in analysis_result.groups:
                # Get all tracks in the group
                canonical_track = None
                duplicate_tracks = []
                similarity_scores = {}
                
                for analysis_track in group.tracks:
                    # Try to get the current track from database
                    current_track = db.session.query(Track).filter(Track.id == analysis_track.track_id).first()
                    
                    if current_track:
                        # Track still exists, use current data
                        track_to_use = current_track
                        # Update existence status
                        analysis_track.still_exists = True
                    else:
                        # Track was deleted, create a temporary track object from snapshot
                        track_to_use = Track(
                            id=analysis_track.track_id,
                            song=analysis_track.song_name,
                            artist=analysis_track.artist_name,
                            album=analysis_track.album_name,
                            play_cnt=analysis_track.play_count,
                            last_play_dt=analysis_track.last_played,
                            date_added=analysis_track.date_added
                        )
                        # Update existence status
                        analysis_track.still_exists = False
                        analysis_track.deleted_at = datetime.now()
                    
                    # Add to appropriate list
                    if analysis_track.is_canonical:
                        canonical_track = track_to_use
                    else:
                        duplicate_tracks.append(track_to_use)
                    
                    # Store similarity score
                    similarity_scores[track_to_use.id] = analysis_track.similarity_score
                
                # Create DuplicateGroup object
                if canonical_track:
                    duplicate_group = DuplicateGroup(
                        canonical_song=canonical_track,
                        duplicates=duplicate_tracks,
                        similarity_scores=similarity_scores,
                        suggested_action=group.suggested_action
                    )
                    duplicate_groups.append(duplicate_group)
            
            # Commit any status updates
            db.session.commit()
            
            return duplicate_groups
            
        except Exception as e:
            db.session.rollback()
            raise Exception(f"Failed to convert analysis result to duplicate groups: {str(e)}")  
  
    def get_analysis_summary(self, analysis_result: DuplicateAnalysisResult) -> Dict:
        """
        Get a summary of the analysis result for display purposes.
        
        Args:
            analysis_result: The analysis result to summarize
            
        Returns:
            Dictionary with summary information
        """
        try:
            # Count resolved and unresolved groups
            resolved_groups = sum(1 for group in analysis_result.groups if group.resolved)
            unresolved_groups = len(analysis_result.groups) - resolved_groups
            
            # Count tracks that still exist
            existing_tracks = 0
            deleted_tracks = 0
            
            for group in analysis_result.groups:
                for track in group.tracks:
                    if track.still_exists:
                        existing_tracks += 1
                    else:
                        deleted_tracks += 1
            
            summary = {
                'analysis_id': analysis_result.analysis_id,
                'created_at': analysis_result.created_at,
                'completed_at': analysis_result.completed_at,
                'status': analysis_result.status,
                'search_term': analysis_result.search_term,
                'sort_by': analysis_result.sort_by,
                'min_confidence': analysis_result.min_confidence,
                'total_groups': analysis_result.total_groups_found,
                'total_duplicates': analysis_result.total_duplicates_found,
                'resolved_groups': resolved_groups,
                'unresolved_groups': unresolved_groups,
                'existing_tracks': existing_tracks,
                'deleted_tracks': deleted_tracks,
                'average_similarity': analysis_result.average_similarity_score,
                'processing_time': analysis_result.processing_time_seconds,
                'library_track_count': analysis_result.library_track_count,
                'library_last_modified': analysis_result.library_last_modified
            }
            
            return summary
            
        except Exception as e:
            raise Exception(f"Failed to get analysis summary: {str(e)}")
    
    def delete_analysis_result(self, analysis_id: str, user_id: int) -> bool:
        """
        Delete an analysis result and all related data.
        
        Args:
            analysis_id: UUID of the analysis to delete
            user_id: ID of the user (for security check)
            
        Returns:
            True if deleted successfully, False if not found or not authorized
        """
        try:
            # Find the analysis result
            analysis_result = db.session.query(DuplicateAnalysisResult)\
                .filter(
                    and_(
                        DuplicateAnalysisResult.analysis_id == analysis_id,
                        DuplicateAnalysisResult.user_id == user_id
                    )
                )\
                .first()
            
            if not analysis_result:
                return False
            
            # Delete the analysis result (cascade will handle related records)
            db.session.delete(analysis_result)
            db.session.commit()
            
            return True
            
        except Exception as e:
            db.session.rollback()
            raise Exception(f"Failed to delete analysis result: {str(e)}")
    
    def update_analysis_metadata(self, analysis_id: str, metadata: Dict) -> bool:
        """
        Update analysis metadata (e.g., user notes, tags).
        
        Args:
            analysis_id: UUID of the analysis to update
            metadata: Dictionary of metadata to update
            
        Returns:
            True if updated successfully, False if not found
        """
        try:
            analysis_result = db.session.query(DuplicateAnalysisResult)\
                .filter(DuplicateAnalysisResult.analysis_id == analysis_id)\
                .first()
            
            if not analysis_result:
                return False
            
            # Update allowed metadata fields
            if 'search_term' in metadata:
                analysis_result.search_term = metadata['search_term']
            
            db.session.commit()
            return True
            
        except Exception as e:
            db.session.rollback()
            raise Exception(f"Failed to update analysis metadata: {str(e)}")


    def update_analysis_status(self, analysis_id: str, status: str, 
                             error_message: Optional[str] = None, 
                             error_details: Optional[Dict] = None) -> bool:
        """
        Update analysis status for tracking analysis progress and completion with error handling.
        
        Args:
            analysis_id: UUID of the analysis to update
            status: New status ('running', 'completed', 'failed', 'cancelled')
            error_message: Optional error message for failed analyses
            error_details: Optional detailed error information
            
        Returns:
            True if updated successfully, False if not found
        """
        def _update_status():
            with self.database_transaction_safety("update analysis status"):
                analysis_result = db.session.query(DuplicateAnalysisResult)\
                    .filter(DuplicateAnalysisResult.analysis_id == analysis_id)\
                    .first()
                
                if not analysis_result:
                    return False
                
                # Update status
                analysis_result.status = status
                
                # Set completion time for completed/failed/cancelled analyses
                if status in ['completed', 'failed', 'cancelled']:
                    analysis_result.completed_at = datetime.now()
                
                # Set error information for failed analyses
                if status == 'failed':
                    analysis_result.error_message = error_message
                    analysis_result.error_details = error_details
                
                return True
        
        try:
            return self.retry_with_backoff(_update_status, f"update analysis status to {status}")
            
        except Exception as e:
            self.logger.error(f"Failed to update analysis status for {analysis_id}: {str(e)}")
            self.logger.debug(f"Update status error details: {traceback.format_exc()}")
            raise Exception(f"Failed to update analysis status: {str(e)}")
    
    def mark_groups_resolved(self, group_ids: List[int], resolution_action: str, 
                           user_id: Optional[int] = None) -> int:
        """
        Mark duplicate groups as resolved to track which groups have been handled.
        
        Args:
            group_ids: List of group IDs to mark as resolved
            resolution_action: Action taken ('deleted', 'kept_canonical', 'manual_review')
            user_id: Optional user ID for security check
            
        Returns:
            Number of groups successfully marked as resolved
        """
        try:
            query = db.session.query(DuplicateAnalysisGroup)\
                .filter(DuplicateAnalysisGroup.id.in_(group_ids))
            
            # Add user security check if provided
            if user_id:
                query = query.join(DuplicateAnalysisResult)\
                    .filter(DuplicateAnalysisResult.user_id == user_id)
            
            groups = query.all()
            
            resolved_count = 0
            for group in groups:
                if not group.resolved:
                    group.resolved = True
                    group.resolved_at = datetime.now()
                    group.resolution_action = resolution_action
                    resolved_count += 1
            
            db.session.commit()
            return resolved_count
            
        except Exception as e:
            db.session.rollback()
            raise Exception(f"Failed to mark groups as resolved: {str(e)}")
    
    def cleanup_old_results(self, retention_days: Optional[int] = None, 
                          max_results_per_user: Optional[int] = None) -> Dict[str, int]:
        """
        Clean up old analysis results with configurable retention policies and storage limits.
        
        Args:
            retention_days: Number of days to retain results (default: self.cleanup_days)
            max_results_per_user: Maximum results per user (default: self.max_results_per_user)
            
        Returns:
            Dictionary with cleanup statistics
        """
        try:
            retention_days = retention_days or self.cleanup_days
            max_results_per_user = max_results_per_user or self.max_results_per_user
            
            cleanup_stats = {
                'deleted_by_age': 0,
                'deleted_by_limit': 0,
                'total_deleted': 0,
                'errors': 0
            }
            
            # Clean up by age
            cutoff_date = datetime.now() - timedelta(days=retention_days)
            old_analyses = db.session.query(DuplicateAnalysisResult)\
                .filter(DuplicateAnalysisResult.created_at < cutoff_date)\
                .all()
            
            for analysis in old_analyses:
                try:
                    db.session.delete(analysis)
                    cleanup_stats['deleted_by_age'] += 1
                except Exception as e:
                    cleanup_stats['errors'] += 1
                    print(f"Error deleting old analysis {analysis.analysis_id}: {str(e)}")
            
            # Clean up by user limits
            users_with_analyses = db.session.query(DuplicateAnalysisResult.user_id)\
                .distinct()\
                .all()
            
            for (user_id,) in users_with_analyses:
                # Get analyses for this user, ordered by creation date (newest first)
                user_analyses = db.session.query(DuplicateAnalysisResult)\
                    .filter(DuplicateAnalysisResult.user_id == user_id)\
                    .order_by(desc(DuplicateAnalysisResult.created_at))\
                    .all()
                
                # Delete excess analyses beyond the limit
                if len(user_analyses) > max_results_per_user:
                    excess_analyses = user_analyses[max_results_per_user:]
                    for analysis in excess_analyses:
                        try:
                            db.session.delete(analysis)
                            cleanup_stats['deleted_by_limit'] += 1
                        except Exception as e:
                            cleanup_stats['errors'] += 1
                            print(f"Error deleting excess analysis {analysis.analysis_id}: {str(e)}")
            
            # Commit all deletions
            db.session.commit()
            
            cleanup_stats['total_deleted'] = cleanup_stats['deleted_by_age'] + cleanup_stats['deleted_by_limit']
            
            return cleanup_stats
            
        except Exception as e:
            db.session.rollback()
            raise Exception(f"Failed to cleanup old results: {str(e)}")
    
    def is_analysis_stale(self, analysis_result: DuplicateAnalysisResult, 
                         staleness_hours: int = 24) -> bool:
        """
        Check if analysis is stale based on configurable staleness thresholds.
        
        Args:
            analysis_result: The analysis result to check
            staleness_hours: Number of hours after which analysis is considered stale
            
        Returns:
            True if analysis is stale, False otherwise
        """
        try:
            if not analysis_result or not analysis_result.created_at:
                return True
            
            staleness_threshold = datetime.now() - timedelta(hours=staleness_hours)
            return analysis_result.created_at < staleness_threshold
            
        except Exception as e:
            raise Exception(f"Failed to check analysis staleness: {str(e)}")
    
    def get_staleness_level(self, analysis_result: DuplicateAnalysisResult) -> str:
        """
        Get staleness level with configurable thresholds for fresh/moderate/stale classifications.
        
        Args:
            analysis_result: The analysis result to check
            
        Returns:
            Staleness level: 'fresh', 'moderate', 'stale', 'very_stale'
        """
        try:
            if not analysis_result or not analysis_result.created_at:
                return 'very_stale'
            
            age_hours = (datetime.now() - analysis_result.created_at).total_seconds() / 3600
            
            if age_hours < 1:
                return 'fresh'
            elif age_hours < 24:
                return 'moderate'
            elif age_hours < 168:  # 1 week
                return 'stale'
            else:
                return 'very_stale'
                
        except Exception as e:
            raise Exception(f"Failed to get staleness level: {str(e)}")
    
    @contextmanager
    def database_transaction_safety(self, operation_name: str):
        """
        Context manager for database transaction safety with atomic saves and rollback on failures.
        
        Args:
            operation_name: Name of the operation for logging
        """
        try:
            # Don't explicitly begin transaction - Flask-SQLAlchemy manages this
            yield
            # Commit if successful
            db.session.commit()
            self.logger.debug(f"Database transaction for {operation_name} committed successfully")
            
        except Exception as e:
            # Rollback on any error
            db.session.rollback()
            self.logger.error(f"Database transaction for {operation_name} rolled back due to error: {str(e)}")
            raise
    
    def retry_with_backoff(self, operation, operation_name: str, *args, **kwargs):
        """
        Execute operation with retry logic for transient database errors and network issues.
        
        Args:
            operation: Function to execute
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
                result = operation(*args, **kwargs)
                
                if attempt > 0:
                    self.logger.info(f"{operation_name} succeeded on attempt {attempt + 1}")
                
                return result
                
            except (OperationalError, IntegrityError, ConnectionError) as e:
                last_exception = e
                self.logger.warning(
                    f"{operation_name} failed on attempt {attempt + 1}/{self.max_retry_attempts}: {str(e)}"
                )
                
                if attempt < self.max_retry_attempts - 1:
                    # Wait before retrying with exponential backoff
                    delay = self.retry_delay_seconds * (2 ** attempt)
                    self.logger.info(f"Retrying {operation_name} in {delay} seconds...")
                    import time
                    time.sleep(delay)
                else:
                    self.logger.error(f"{operation_name} failed after {self.max_retry_attempts} attempts")
            
            except Exception as e:
                # For other exceptions, log and re-raise immediately
                self.logger.error(f"{operation_name} failed with non-retryable error: {str(e)}")
                raise
        
        # If we get here, all retries failed
        raise last_exception

    def get_analysis_age_info(self, analysis_result: DuplicateAnalysisResult) -> Dict:
        """
        Get detailed age information with user-friendly formatting and color-coded indicators.
        
        Args:
            analysis_result: The analysis result to analyze
            
        Returns:
            Dictionary with age information and display formatting
        """
        try:
            if not analysis_result or not analysis_result.created_at:
                return {
                    'age_text': 'Unknown age',
                    'age_hours': 0,
                    'staleness_level': 'very_stale',
                    'color_class': 'text-danger',
                    'icon': 'fas fa-exclamation-triangle',
                    'needs_refresh': True
                }
            
            now = datetime.now()
            age_delta = now - analysis_result.created_at
            age_hours = age_delta.total_seconds() / 3600
            age_days = age_delta.days
            
            # Format age text
            if age_hours < 1:
                age_text = f"{int(age_delta.total_seconds() / 60)} minutes ago"
            elif age_hours < 24:
                age_text = f"{int(age_hours)} hours ago"
            elif age_days == 1:
                age_text = "1 day ago"
            else:
                age_text = f"{age_days} days ago"
            
            staleness_level = self.get_staleness_level(analysis_result)
            
            # Determine display properties based on staleness
            if staleness_level == 'fresh':
                color_class = 'text-success'
                icon = 'fas fa-check-circle'
                needs_refresh = False
            elif staleness_level == 'moderate':
                color_class = 'text-warning'
                icon = 'fas fa-clock'
                needs_refresh = False
            elif staleness_level == 'stale':
                color_class = 'text-warning'
                icon = 'fas fa-exclamation-triangle'
                needs_refresh = True
            else:  # very_stale
                color_class = 'text-danger'
                icon = 'fas fa-exclamation-triangle'
                needs_refresh = True
            
            return {
                'age_text': age_text,
                'age_hours': age_hours,
                'age_days': age_days,
                'staleness_level': staleness_level,
                'color_class': color_class,
                'icon': icon,
                'needs_refresh': needs_refresh,
                'created_at_formatted': analysis_result.created_at.strftime('%B %d, %Y at %I:%M %p')
            }
            
        except Exception as e:
            raise Exception(f"Failed to get analysis age info: {str(e)}")
    
    def get_library_change_summary(self, analysis_result: DuplicateAnalysisResult) -> Dict:
        """
        Get summary of library changes since analysis was performed.
        
        Args:
            analysis_result: The analysis result to compare against
            
        Returns:
            Dictionary with library change information
        """
        try:
            if not analysis_result or not analysis_result.created_at:
                return {
                    'tracks_added': 0,
                    'tracks_modified': 0,
                    'tracks_deleted': 0,
                    'total_changes': 0,
                    'change_percentage': 0.0,
                    'significant_change': False,
                    'last_analysis_track_count': 0,
                    'current_track_count': 0
                }
            
            analysis_date = analysis_result.created_at
            current_track_count = db.session.query(Track).count()
            last_analysis_track_count = analysis_result.library_track_count or 0
            
            # Count tracks added since analysis
            tracks_added = db.session.query(Track)\
                .filter(Track.date_added > analysis_date)\
                .count() if analysis_date else 0
            
            # Count tracks modified since analysis (using last_play_dt as proxy for modification)
            tracks_modified = db.session.query(Track)\
                .filter(
                    and_(
                        Track.date_added <= analysis_date,
                        Track.last_play_dt > analysis_date
                    )
                )\
                .count() if analysis_date else 0
            
            # Estimate deleted tracks (tracks that were in analysis but no longer exist)
            tracks_deleted = max(0, last_analysis_track_count - current_track_count + tracks_added)
            
            total_changes = tracks_added + tracks_modified + tracks_deleted
            
            # Calculate change percentage
            change_percentage = 0.0
            if last_analysis_track_count > 0:
                change_percentage = (total_changes / last_analysis_track_count) * 100
            
            # Determine if change is significant (>10% change or >50 tracks)
            significant_change = change_percentage > 10 or total_changes > 50
            
            return {
                'tracks_added': tracks_added,
                'tracks_modified': tracks_modified,
                'tracks_deleted': tracks_deleted,
                'total_changes': total_changes,
                'change_percentage': round(change_percentage, 1),
                'significant_change': significant_change,
                'last_analysis_track_count': last_analysis_track_count,
                'current_track_count': current_track_count,
                'analysis_date': analysis_date
            }
            
        except Exception as e:
            raise Exception(f"Failed to get library change summary: {str(e)}")
    
    def get_refresh_recommendations(self, analysis_result: DuplicateAnalysisResult) -> Dict:
        """
        Get recommendations for whether user should refresh based on age and library changes.
        
        Args:
            analysis_result: The analysis result to analyze
            
        Returns:
            Dictionary with refresh recommendations and reasoning
        """
        try:
            age_info = self.get_analysis_age_info(analysis_result)
            library_changes = self.get_library_change_summary(analysis_result)
            
            recommendations = {
                'should_refresh': False,
                'urgency': 'low',  # low, medium, high
                'reasons': [],
                'suggested_action': 'continue',  # continue, refresh, new_analysis
                'message': '',
                'age_info': age_info,
                'library_changes': library_changes
            }
            
            # Check age-based recommendations
            if age_info['staleness_level'] == 'very_stale':
                recommendations['should_refresh'] = True
                recommendations['urgency'] = 'high'
                recommendations['reasons'].append(f"Analysis is {age_info['age_text']} - very outdated")
                recommendations['suggested_action'] = 'refresh'
            elif age_info['staleness_level'] == 'stale':
                recommendations['should_refresh'] = True
                recommendations['urgency'] = 'medium'
                recommendations['reasons'].append(f"Analysis is {age_info['age_text']} - consider refreshing")
                recommendations['suggested_action'] = 'refresh'
            
            # Check library change-based recommendations
            if library_changes['significant_change']:
                recommendations['should_refresh'] = True
                if library_changes['change_percentage'] > 20:
                    recommendations['urgency'] = 'high'
                    recommendations['reasons'].append(f"Library has changed significantly ({library_changes['change_percentage']}% change)")
                else:
                    if recommendations['urgency'] == 'low':
                        recommendations['urgency'] = 'medium'
                    recommendations['reasons'].append(f"Library has changed moderately ({library_changes['total_changes']} tracks)")
                
                if recommendations['suggested_action'] == 'continue':
                    recommendations['suggested_action'] = 'refresh'
            
            # Add specific change details to reasons
            if library_changes['tracks_added'] > 0:
                recommendations['reasons'].append(f"{library_changes['tracks_added']} tracks added")
            if library_changes['tracks_modified'] > 0:
                recommendations['reasons'].append(f"{library_changes['tracks_modified']} tracks modified")
            if library_changes['tracks_deleted'] > 0:
                recommendations['reasons'].append(f"{library_changes['tracks_deleted']} tracks deleted")
            
            # Generate message
            if recommendations['should_refresh']:
                if recommendations['urgency'] == 'high':
                    recommendations['message'] = "We strongly recommend refreshing this analysis."
                elif recommendations['urgency'] == 'medium':
                    recommendations['message'] = "Consider refreshing this analysis for more accurate results."
                else:
                    recommendations['message'] = "You may want to refresh this analysis."
            else:
                recommendations['message'] = "This analysis appears to be current."
            
            return recommendations
            
        except Exception as e:
            raise Exception(f"Failed to get refresh recommendations: {str(e)}")


    def get_library_modification_timestamp(self) -> Optional[datetime]:
        """
        Get the most recent library modification timestamp for efficient change detection.
        
        Returns:
            Most recent modification timestamp or None if no tracks exist
        """
        try:
            # Get the most recent date_added or last_play_dt as proxy for modification
            most_recent_added = db.session.query(func.max(Track.date_added)).scalar()
            most_recent_played = db.session.query(func.max(Track.last_play_dt)).scalar()
            
            # Return the most recent of the two timestamps
            if most_recent_added and most_recent_played:
                return max(most_recent_added, most_recent_played)
            elif most_recent_added:
                return most_recent_added
            elif most_recent_played:
                return most_recent_played
            else:
                return None
                
        except Exception as e:
            raise Exception(f"Failed to get library modification timestamp: {str(e)}")
    
    def get_staleness_warnings(self, analysis_result: DuplicateAnalysisResult, 
                             user_preferences: Optional[Dict] = None) -> Dict:
        """
        Generate automatic staleness warnings with suggested actions based on library changes.
        
        Args:
            analysis_result: The analysis result to check
            user_preferences: Optional user preferences for staleness notifications
            
        Returns:
            Dictionary with warning information and suggested actions
        """
        try:
            # Default preferences
            default_preferences = {
                'staleness_threshold_hours': 24,
                'change_threshold_percentage': 10,
                'change_threshold_count': 50,
                'show_age_warnings': True,
                'show_change_warnings': True,
                'auto_suggest_refresh': True
            }
            
            preferences = {**default_preferences, **(user_preferences or {})}
            
            age_info = self.get_analysis_age_info(analysis_result)
            library_changes = self.get_library_change_summary(analysis_result)
            
            warnings = {
                'has_warnings': False,
                'age_warning': None,
                'change_warning': None,
                'suggested_actions': [],
                'warning_level': 'none',  # none, info, warning, danger
                'show_banner': False
            }
            
            # Check age-based warnings
            if preferences['show_age_warnings'] and age_info['age_hours'] > preferences['staleness_threshold_hours']:
                warnings['has_warnings'] = True
                warnings['age_warning'] = {
                    'message': f"This analysis is {age_info['age_text']} and may be outdated.",
                    'level': 'warning' if age_info['staleness_level'] == 'stale' else 'danger',
                    'icon': age_info['icon']
                }
                warnings['warning_level'] = warnings['age_warning']['level']
                warnings['show_banner'] = True
            
            # Check change-based warnings
            if preferences['show_change_warnings']:
                change_percentage = library_changes['change_percentage']
                total_changes = library_changes['total_changes']
                
                if (change_percentage > preferences['change_threshold_percentage'] or 
                    total_changes > preferences['change_threshold_count']):
                    
                    warnings['has_warnings'] = True
                    
                    # Build change message
                    change_details = []
                    if library_changes['tracks_added'] > 0:
                        change_details.append(f"{library_changes['tracks_added']} tracks added")
                    if library_changes['tracks_modified'] > 0:
                        change_details.append(f"{library_changes['tracks_modified']} tracks modified")
                    if library_changes['tracks_deleted'] > 0:
                        change_details.append(f"{library_changes['tracks_deleted']} tracks deleted")
                    
                    change_message = f"Your library has changed since this analysis: {', '.join(change_details)}."
                    
                    warning_level = 'danger' if change_percentage > 20 else 'warning'
                    
                    warnings['change_warning'] = {
                        'message': change_message,
                        'level': warning_level,
                        'icon': 'fas fa-exclamation-triangle',
                        'percentage': change_percentage,
                        'total_changes': total_changes
                    }
                    
                    # Update overall warning level to highest severity
                    if warning_level == 'danger' or warnings['warning_level'] == 'none':
                        warnings['warning_level'] = warning_level
                    
                    warnings['show_banner'] = True
            
            # Generate suggested actions
            if preferences['auto_suggest_refresh'] and warnings['has_warnings']:
                if warnings['warning_level'] == 'danger':
                    warnings['suggested_actions'].append({
                        'action': 'refresh',
                        'text': 'Refresh Analysis',
                        'class': 'btn-danger',
                        'icon': 'fas fa-sync-alt',
                        'primary': True
                    })
                    warnings['suggested_actions'].append({
                        'action': 'new_analysis',
                        'text': 'New Analysis',
                        'class': 'btn-secondary',
                        'icon': 'fas fa-plus',
                        'primary': False
                    })
                else:
                    warnings['suggested_actions'].append({
                        'action': 'refresh',
                        'text': 'Refresh Analysis',
                        'class': 'btn-warning',
                        'icon': 'fas fa-sync-alt',
                        'primary': True
                    })
                    warnings['suggested_actions'].append({
                        'action': 'continue',
                        'text': 'Continue with Current',
                        'class': 'btn-outline-secondary',
                        'icon': 'fas fa-arrow-right',
                        'primary': False
                    })
            
            return warnings
            
        except Exception as e:
            raise Exception(f"Failed to get staleness warnings: {str(e)}")
    
    def save_user_staleness_preferences(self, user_id: int, preferences: Dict) -> bool:
        """
        Save user preferences for staleness notification settings.
        
        Args:
            user_id: ID of the user
            preferences: Dictionary of preference settings
            
        Returns:
            True if saved successfully, False otherwise
        """
        try:
            # Validate preferences
            valid_keys = {
                'staleness_threshold_hours', 'change_threshold_percentage', 
                'change_threshold_count', 'show_age_warnings', 
                'show_change_warnings', 'auto_suggest_refresh'
            }
            
            filtered_preferences = {k: v for k, v in preferences.items() if k in valid_keys}
            
            # Get or create user preferences record
            user_prefs = db.session.query(UserPreferences)\
                .filter(UserPreferences.user_id == user_id)\
                .first()
            
            if not user_prefs:
                user_prefs = UserPreferences(user_id=user_id)
                db.session.add(user_prefs)
            
            # Update preferences
            for key, value in filtered_preferences.items():
                if hasattr(user_prefs, key):
                    setattr(user_prefs, key, value)
            
            # Update timestamp
            user_prefs.updated_at = datetime.now()
            
            db.session.commit()
            return True
            
        except Exception as e:
            db.session.rollback()
            raise Exception(f"Failed to save user staleness preferences: {str(e)}")
    
    def get_user_staleness_preferences(self, user_id: int) -> Dict:
        """
        Get user preferences for staleness notification settings.
        
        Args:
            user_id: ID of the user
            
        Returns:
            Dictionary of user preferences with defaults for missing values
        """
        try:
            # Default preferences
            default_preferences = {
                'staleness_threshold_hours': 24,
                'change_threshold_percentage': 10.0,
                'change_threshold_count': 50,
                'show_age_warnings': True,
                'show_change_warnings': True,
                'auto_suggest_refresh': True
            }
            
            # Load user preferences from database
            user_prefs = db.session.query(UserPreferences)\
                .filter(UserPreferences.user_id == user_id)\
                .first()
            
            if user_prefs:
                # Convert model to dictionary
                user_preferences = {
                    'staleness_threshold_hours': user_prefs.staleness_threshold_hours,
                    'change_threshold_percentage': user_prefs.change_threshold_percentage,
                    'change_threshold_count': user_prefs.change_threshold_count,
                    'show_age_warnings': user_prefs.show_age_warnings,
                    'show_change_warnings': user_prefs.show_change_warnings,
                    'auto_suggest_refresh': user_prefs.auto_suggest_refresh
                }
                
                # Merge with defaults for any missing values
                return {**default_preferences, **user_preferences}
            else:
                # Return defaults if no preferences found
                return default_preferences
            
        except Exception as e:
            raise Exception(f"Failed to get user staleness preferences: {str(e)}")

    def export_analysis_results(self, analysis_id: str, format: str = 'json', 
                              user_id: Optional[int] = None, 
                              progress_callback: Optional[callable] = None) -> Dict:
        """
        Export analysis results supporting JSON and CSV formats with comprehensive data.
        
        Args:
            analysis_id: UUID of the analysis to export
            format: Export format ('json' or 'csv')
            user_id: Optional user ID for security check
            progress_callback: Optional callback for progress tracking
            
        Returns:
            Dictionary with export information including file path, size, and metadata
        """
        try:
            # Load analysis result with all related data
            query = db.session.query(DuplicateAnalysisResult)\
                .options(
                    joinedload(DuplicateAnalysisResult.groups)
                    .joinedload(DuplicateAnalysisGroup.tracks)
                )\
                .filter(DuplicateAnalysisResult.analysis_id == analysis_id)
            
            # Add user security check if provided
            if user_id:
                query = query.filter(DuplicateAnalysisResult.user_id == user_id)
            
            analysis_result = query.first()
            
            if not analysis_result:
                raise Exception(f"Analysis {analysis_id} not found or access denied")
            
            # Update progress
            if progress_callback:
                progress_callback("Preparing export data", 0, 100)
            
            # Prepare export data
            export_data = self._prepare_export_data(analysis_result, progress_callback)
            
            # Generate export ID and filename
            export_id = str(uuid.uuid4())
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"duplicate_analysis_{analysis_id[:8]}_{timestamp}.{format}"
            
            # Create temporary file
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, filename)
            
            # Export based on format
            if format.lower() == 'json':
                file_size = self._export_to_json(export_data, file_path, progress_callback)
            elif format.lower() == 'csv':
                file_size = self._export_to_csv(export_data, file_path, progress_callback)
            else:
                raise Exception(f"Unsupported export format: {format}")
            
            # Create export tracking record
            export_record = DuplicateAnalysisExport(
                export_id=export_id,
                analysis_id=analysis_id,
                user_id=user_id or analysis_result.user_id,
                format=format.lower(),
                filename=filename,
                file_size=file_size,
                file_path=file_path,
                expires_at=datetime.now() + timedelta(hours=24)  # Expire after 24 hours
            )
            
            db.session.add(export_record)
            db.session.commit()
            
            # Update progress
            if progress_callback:
                progress_callback("Export completed", 100, 100)
            
            return {
                'success': True,
                'export_id': export_id,
                'file_path': file_path,
                'filename': filename,
                'format': format,
                'file_size': file_size,
                'file_size_mb': round(file_size / (1024 * 1024), 2),
                'analysis_id': analysis_id,
                'created_at': datetime.now().isoformat(),
                'expires_at': export_record.expires_at.isoformat(),
                'total_groups': len(analysis_result.groups),
                'total_tracks': sum(len(group.tracks) for group in analysis_result.groups)
            }
            
        except Exception as e:
            db.session.rollback()
            raise Exception(f"Failed to export analysis results: {str(e)}")
    
    def _prepare_export_data(self, analysis_result: DuplicateAnalysisResult, 
                           progress_callback: Optional[callable] = None) -> Dict:
        """
        Prepare comprehensive export data including duplicate groups, metadata, and iTunes match status.
        
        Args:
            analysis_result: The analysis result to export
            progress_callback: Optional callback for progress tracking
            
        Returns:
            Dictionary with structured export data
        """
        try:
            # Update progress
            if progress_callback:
                progress_callback("Preparing analysis metadata", 10, 100)
            
            # Prepare analysis metadata
            export_data = {
                'analysis_metadata': {
                    'analysis_id': analysis_result.analysis_id,
                    'created_at': analysis_result.created_at.isoformat() if analysis_result.created_at else None,
                    'completed_at': analysis_result.completed_at.isoformat() if analysis_result.completed_at else None,
                    'status': analysis_result.status,
                    'search_term': analysis_result.search_term,
                    'sort_by': analysis_result.sort_by,
                    'min_confidence': analysis_result.min_confidence,
                    'total_tracks_analyzed': analysis_result.total_tracks_analyzed,
                    'total_groups_found': analysis_result.total_groups_found,
                    'total_duplicates_found': analysis_result.total_duplicates_found,
                    'average_similarity_score': analysis_result.average_similarity_score,
                    'processing_time_seconds': analysis_result.processing_time_seconds,
                    'library_track_count': analysis_result.library_track_count,
                    'library_last_modified': analysis_result.library_last_modified.isoformat() if analysis_result.library_last_modified else None
                },
                'duplicate_groups': [],
                'export_metadata': {
                    'exported_at': datetime.now().isoformat(),
                    'export_version': '1.0',
                    'total_groups': len(analysis_result.groups),
                    'total_tracks': 0
                }
            }
            
            # Update progress
            if progress_callback:
                progress_callback("Processing duplicate groups", 20, 100)
            
            total_tracks = 0
            total_groups = len(analysis_result.groups)
            
            # Process each duplicate group
            for group_index, group in enumerate(analysis_result.groups):
                # Update progress
                if progress_callback and group_index % 10 == 0:
                    progress = 20 + int((group_index / total_groups) * 60)
                    progress_callback(f"Processing group {group_index + 1} of {total_groups}", progress, 100)
                
                group_data = {
                    'group_index': group.group_index,
                    'canonical_track_id': group.canonical_track_id,
                    'duplicate_count': group.duplicate_count,
                    'average_similarity_score': group.average_similarity_score,
                    'suggested_action': group.suggested_action,
                    'has_itunes_matches': group.has_itunes_matches,
                    'itunes_match_data': group.itunes_match_data,
                    'resolved': group.resolved,
                    'resolved_at': group.resolved_at.isoformat() if group.resolved_at else None,
                    'resolution_action': group.resolution_action,
                    'tracks': []
                }
                
                # Process tracks in the group
                for track in group.tracks:
                    track_data = {
                        'track_id': track.track_id,
                        'song_name': track.song_name,
                        'artist_name': track.artist_name,
                        'album_name': track.album_name,
                        'play_count': track.play_count,
                        'last_played': track.last_played.isoformat() if track.last_played else None,
                        'date_added': track.date_added.isoformat() if track.date_added else None,
                        'similarity_score': track.similarity_score,
                        'is_canonical': track.is_canonical,
                        'itunes_match_found': track.itunes_match_found,
                        'itunes_match_confidence': track.itunes_match_confidence,
                        'itunes_match_type': track.itunes_match_type,
                        'still_exists': track.still_exists,
                        'deleted_at': track.deleted_at.isoformat() if track.deleted_at else None
                    }
                    
                    group_data['tracks'].append(track_data)
                    total_tracks += 1
                
                export_data['duplicate_groups'].append(group_data)
            
            # Update export metadata
            export_data['export_metadata']['total_tracks'] = total_tracks
            
            # Update progress
            if progress_callback:
                progress_callback("Export data prepared", 80, 100)
            
            return export_data
            
        except Exception as e:
            raise Exception(f"Failed to prepare export data: {str(e)}")
    
    def _export_to_json(self, export_data: Dict, file_path: str, 
                       progress_callback: Optional[callable] = None) -> int:
        """
        Export data to JSON format with secure temporary file generation.
        
        Args:
            export_data: Prepared export data
            file_path: Path to write the JSON file
            progress_callback: Optional callback for progress tracking
            
        Returns:
            File size in bytes
        """
        try:
            # Update progress
            if progress_callback:
                progress_callback("Writing JSON file", 85, 100)
            
            # Write JSON file with proper formatting
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)
            
            # Get file size
            file_size = os.path.getsize(file_path)
            
            # Update progress
            if progress_callback:
                progress_callback("JSON export completed", 95, 100)
            
            return file_size
            
        except Exception as e:
            # Clean up file on error
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
            raise Exception(f"Failed to export to JSON: {str(e)}")
    
    def _export_to_csv(self, export_data: Dict, file_path: str, 
                      progress_callback: Optional[callable] = None) -> int:
        """
        Export data to CSV format with flattened structure for spreadsheet compatibility.
        
        Args:
            export_data: Prepared export data
            file_path: Path to write the CSV file
            progress_callback: Optional callback for progress tracking
            
        Returns:
            File size in bytes
        """
        try:
            # Update progress
            if progress_callback:
                progress_callback("Writing CSV file", 85, 100)
            
            # Define CSV headers
            headers = [
                'analysis_id', 'analysis_created_at', 'analysis_status',
                'search_term', 'sort_by', 'min_confidence',
                'group_index', 'group_canonical_track_id', 'group_duplicate_count',
                'group_average_similarity', 'group_suggested_action', 'group_resolved',
                'group_resolution_action', 'group_has_itunes_matches',
                'track_id', 'track_song_name', 'track_artist_name', 'track_album_name',
                'track_play_count', 'track_last_played', 'track_date_added',
                'track_similarity_score', 'track_is_canonical', 'track_still_exists',
                'track_itunes_match_found', 'track_itunes_match_confidence', 'track_itunes_match_type'
            ]
            
            # Write CSV file
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                # Write headers
                writer.writerow(headers)
                
                # Write data rows
                analysis_metadata = export_data['analysis_metadata']
                total_groups = len(export_data['duplicate_groups'])
                
                for group_index, group in enumerate(export_data['duplicate_groups']):
                    # Update progress
                    if progress_callback and group_index % 10 == 0:
                        progress = 85 + int((group_index / total_groups) * 10)
                        progress_callback(f"Writing CSV group {group_index + 1} of {total_groups}", progress, 100)
                    
                    for track in group['tracks']:
                        row = [
                            analysis_metadata['analysis_id'],
                            analysis_metadata['created_at'],
                            analysis_metadata['status'],
                            analysis_metadata['search_term'] or '',
                            analysis_metadata['sort_by'],
                            analysis_metadata['min_confidence'],
                            group['group_index'],
                            group['canonical_track_id'],
                            group['duplicate_count'],
                            group['average_similarity_score'],
                            group['suggested_action'],
                            group['resolved'],
                            group['resolution_action'] or '',
                            group['has_itunes_matches'],
                            track['track_id'],
                            track['song_name'] or '',
                            track['artist_name'] or '',
                            track['album_name'] or '',
                            track['play_count'] or 0,
                            track['last_played'] or '',
                            track['date_added'] or '',
                            track['similarity_score'],
                            track['is_canonical'],
                            track['still_exists'],
                            track['itunes_match_found'],
                            track['itunes_match_confidence'] or '',
                            track['itunes_match_type'] or ''
                        ]
                        writer.writerow(row)
            
            # Get file size
            file_size = os.path.getsize(file_path)
            
            # Update progress
            if progress_callback:
                progress_callback("CSV export completed", 95, 100)
            
            return file_size
            
        except Exception as e:
            # Clean up file on error
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
            raise Exception(f"Failed to export to CSV: {str(e)}")
    
    def cleanup_export_file(self, file_path: str) -> bool:
        """
        Clean up temporary export file with automatic cleanup.
        
        Args:
            file_path: Path to the file to clean up
            
        Returns:
            True if file was deleted successfully, False otherwise
        """
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                return True
            return False
            
        except Exception as e:
            print(f"Warning: Failed to cleanup export file: {str(e)}")
            return False

    # ============================================================================
    # Resolution Tracking and Impact Management
    # ============================================================================
    
    def update_resolution_status_on_track_deletion(self, deleted_track_ids: List[int], 
                                                 user_id: Optional[int] = None) -> Dict:
        """
        Update resolution status when tracks are deleted to mark resolved duplicates.
        
        Args:
            deleted_track_ids: List of track IDs that were deleted
            user_id: Optional user ID for filtering analyses
            
        Returns:
            Dictionary with update statistics and affected analyses
        """
        try:
            # Find all analysis tracks that reference the deleted tracks
            query = db.session.query(DuplicateAnalysisTrack)\
                .filter(DuplicateAnalysisTrack.track_id.in_(deleted_track_ids))\
                .filter(DuplicateAnalysisTrack.still_exists == True)
            
            # Join with analysis result to filter by user if provided
            if user_id:
                query = query.join(DuplicateAnalysisGroup)\
                    .join(DuplicateAnalysisResult)\
                    .filter(DuplicateAnalysisResult.user_id == user_id)
            
            affected_tracks = query.all()
            
            if not affected_tracks:
                return {
                    'updated_tracks': 0,
                    'updated_groups': 0,
                    'affected_analyses': [],
                    'resolution_summary': {}
                }
            
            # Group tracks by their analysis groups
            affected_groups = {}
            affected_analyses = set()
            
            for track in affected_tracks:
                # Mark track as deleted
                track.still_exists = False
                track.deleted_at = datetime.now()
                
                # Group by analysis group
                group_id = track.group_id
                if group_id not in affected_groups:
                    affected_groups[group_id] = {
                        'group': track.group,
                        'deleted_tracks': [],
                        'remaining_tracks': []
                    }
                
                affected_groups[group_id]['deleted_tracks'].append(track)
                affected_analyses.add(track.group.analysis_id)
            
            # Analyze each affected group to determine resolution status
            updated_groups = 0
            resolution_summary = {
                'fully_resolved': 0,
                'partially_resolved': 0,
                'canonical_deleted': 0,
                'all_deleted': 0
            }
            
            for group_id, group_info in affected_groups.items():
                group = group_info['group']
                deleted_tracks = group_info['deleted_tracks']
                
                # Get all tracks in the group (including those not deleted)
                all_group_tracks = db.session.query(DuplicateAnalysisTrack)\
                    .filter(DuplicateAnalysisTrack.group_id == group_id)\
                    .all()
                
                # Categorize tracks
                canonical_track = None
                remaining_tracks = []
                deleted_track_ids_in_group = set()
                
                for track in all_group_tracks:
                    if track.is_canonical:
                        canonical_track = track
                    
                    if track.still_exists:
                        remaining_tracks.append(track)
                    else:
                        deleted_track_ids_in_group.add(track.track_id)
                
                # Determine resolution action based on what was deleted
                resolution_action = None
                should_mark_resolved = False
                
                if len(remaining_tracks) == 0:
                    # All tracks in group were deleted
                    resolution_action = 'all_deleted'
                    should_mark_resolved = True
                    resolution_summary['all_deleted'] += 1
                    
                elif canonical_track and not canonical_track.still_exists:
                    # Canonical track was deleted
                    if len(remaining_tracks) == 1:
                        # Only one track remains, group is resolved
                        resolution_action = 'canonical_deleted'
                        should_mark_resolved = True
                        resolution_summary['canonical_deleted'] += 1
                    else:
                        # Multiple tracks remain, partially resolved
                        resolution_action = 'canonical_deleted'
                        resolution_summary['partially_resolved'] += 1
                        
                elif len(remaining_tracks) == 1:
                    # Only canonical track remains, duplicates deleted
                    resolution_action = 'duplicates_deleted'
                    should_mark_resolved = True
                    resolution_summary['fully_resolved'] += 1
                    
                else:
                    # Some duplicates deleted but group still has multiple tracks
                    resolution_action = 'partial_cleanup'
                    resolution_summary['partially_resolved'] += 1
                
                # Update group resolution status if appropriate
                if should_mark_resolved and not group.resolved:
                    group.resolved = True
                    group.resolved_at = datetime.now()
                    group.resolution_action = resolution_action
                    updated_groups += 1
                elif resolution_action and not group.resolution_action:
                    # Update resolution action even if not fully resolved
                    group.resolution_action = resolution_action
            
            # Commit all changes
            db.session.commit()
            
            return {
                'updated_tracks': len(affected_tracks),
                'updated_groups': updated_groups,
                'affected_analyses': list(affected_analyses),
                'resolution_summary': resolution_summary,
                'deleted_track_count': len(deleted_track_ids)
            }
            
        except Exception as e:
            db.session.rollback()
            raise Exception(f"Failed to update resolution status on track deletion: {str(e)}")
    
    def get_impact_summary(self, analysis_id: str) -> Dict:
        """
        Get impact summary showing cleanup progress and remaining duplicates.
        
        Args:
            analysis_id: UUID of the analysis to summarize
            
        Returns:
            Dictionary with comprehensive impact information
        """
        try:
            # Load analysis with groups and tracks
            analysis_result = db.session.query(DuplicateAnalysisResult)\
                .options(
                    joinedload(DuplicateAnalysisResult.groups)
                    .joinedload(DuplicateAnalysisGroup.tracks)
                )\
                .filter(DuplicateAnalysisResult.analysis_id == analysis_id)\
                .first()
            
            if not analysis_result:
                raise Exception(f"Analysis {analysis_id} not found")
            
            # Initialize counters
            impact_summary = {
                'analysis_id': analysis_id,
                'analysis_date': analysis_result.created_at,
                'original_stats': {
                    'total_groups': analysis_result.total_groups_found,
                    'total_duplicates': analysis_result.total_duplicates_found,
                    'total_tracks_analyzed': analysis_result.total_tracks_analyzed
                },
                'current_stats': {
                    'resolved_groups': 0,
                    'unresolved_groups': 0,
                    'partially_resolved_groups': 0,
                    'tracks_deleted': 0,
                    'tracks_remaining': 0,
                    'canonical_tracks_deleted': 0,
                    'duplicate_tracks_deleted': 0
                },
                'resolution_breakdown': {
                    'fully_resolved': 0,
                    'duplicates_deleted': 0,
                    'canonical_deleted': 0,
                    'all_deleted': 0,
                    'partial_cleanup': 0,
                    'no_action': 0
                },
                'cleanup_effectiveness': {
                    'groups_resolved_percentage': 0.0,
                    'duplicates_eliminated_percentage': 0.0,
                    'tracks_cleaned_percentage': 0.0
                },
                'recommendations': []
            }
            
            # Analyze each group
            for group in analysis_result.groups:
                # Count tracks by status
                canonical_track = None
                duplicate_tracks = []
                deleted_tracks = []
                remaining_tracks = []
                
                for track in group.tracks:
                    if track.is_canonical:
                        canonical_track = track
                    else:
                        duplicate_tracks.append(track)
                    
                    if track.still_exists:
                        remaining_tracks.append(track)
                    else:
                        deleted_tracks.append(track)
                
                # Update counters
                impact_summary['current_stats']['tracks_deleted'] += len(deleted_tracks)
                impact_summary['current_stats']['tracks_remaining'] += len(remaining_tracks)
                
                if canonical_track and not canonical_track.still_exists:
                    impact_summary['current_stats']['canonical_tracks_deleted'] += 1
                
                duplicate_tracks_deleted = sum(1 for track in deleted_tracks if not track.is_canonical)
                impact_summary['current_stats']['duplicate_tracks_deleted'] += duplicate_tracks_deleted
                
                # Categorize group resolution status
                if group.resolved:
                    impact_summary['current_stats']['resolved_groups'] += 1
                    
                    # Count by resolution action
                    action = group.resolution_action or 'unknown'
                    if action in impact_summary['resolution_breakdown']:
                        impact_summary['resolution_breakdown'][action] += 1
                    else:
                        impact_summary['resolution_breakdown']['fully_resolved'] += 1
                        
                elif len(deleted_tracks) > 0:
                    # Group has some deletions but isn't marked as resolved
                    impact_summary['current_stats']['partially_resolved_groups'] += 1
                    impact_summary['resolution_breakdown']['partial_cleanup'] += 1
                else:
                    # No action taken on this group
                    impact_summary['current_stats']['unresolved_groups'] += 1
                    impact_summary['resolution_breakdown']['no_action'] += 1
            
            # Calculate effectiveness percentages
            total_groups = impact_summary['original_stats']['total_groups']
            total_duplicates = impact_summary['original_stats']['total_duplicates']
            
            if total_groups > 0:
                resolved_percentage = (impact_summary['current_stats']['resolved_groups'] / total_groups) * 100
                impact_summary['cleanup_effectiveness']['groups_resolved_percentage'] = round(resolved_percentage, 1)
            
            if total_duplicates > 0:
                duplicates_eliminated = impact_summary['current_stats']['duplicate_tracks_deleted']
                eliminated_percentage = (duplicates_eliminated / total_duplicates) * 100
                impact_summary['cleanup_effectiveness']['duplicates_eliminated_percentage'] = round(eliminated_percentage, 1)
            
            total_tracks_in_analysis = sum(len(group.tracks) for group in analysis_result.groups)
            if total_tracks_in_analysis > 0:
                tracks_cleaned_percentage = (impact_summary['current_stats']['tracks_deleted'] / total_tracks_in_analysis) * 100
                impact_summary['cleanup_effectiveness']['tracks_cleaned_percentage'] = round(tracks_cleaned_percentage, 1)
            
            # Generate recommendations
            impact_summary['recommendations'] = self._generate_cleanup_recommendations(impact_summary)
            
            return impact_summary
            
        except Exception as e:
            raise Exception(f"Failed to get impact summary: {str(e)}")
    
    def _generate_cleanup_recommendations(self, impact_summary: Dict) -> List[Dict]:
        """
        Generate recommendations for additional cleanup based on resolution patterns.
        
        Args:
            impact_summary: Impact summary data
            
        Returns:
            List of recommendation dictionaries
        """
        recommendations = []
        
        current_stats = impact_summary['current_stats']
        effectiveness = impact_summary['cleanup_effectiveness']
        resolution_breakdown = impact_summary['resolution_breakdown']
        
        # Recommendation based on overall progress
        if effectiveness['groups_resolved_percentage'] < 25:
            recommendations.append({
                'type': 'low_progress',
                'priority': 'high',
                'title': 'Low Cleanup Progress',
                'message': f"Only {effectiveness['groups_resolved_percentage']}% of duplicate groups have been resolved. Consider reviewing and cleaning up more duplicates.",
                'action': 'continue_cleanup',
                'icon': 'fas fa-exclamation-triangle'
            })
        elif effectiveness['groups_resolved_percentage'] < 50:
            recommendations.append({
                'type': 'moderate_progress',
                'priority': 'medium',
                'title': 'Moderate Cleanup Progress',
                'message': f"{effectiveness['groups_resolved_percentage']}% of duplicate groups resolved. You're making good progress!",
                'action': 'continue_cleanup',
                'icon': 'fas fa-chart-line'
            })
        else:
            recommendations.append({
                'type': 'good_progress',
                'priority': 'low',
                'title': 'Good Cleanup Progress',
                'message': f"Excellent! {effectiveness['groups_resolved_percentage']}% of duplicate groups have been resolved.",
                'action': 'maintain_progress',
                'icon': 'fas fa-check-circle'
            })
        
        # Recommendation for unresolved groups
        if current_stats['unresolved_groups'] > 0:
            recommendations.append({
                'type': 'unresolved_groups',
                'priority': 'medium',
                'title': 'Unresolved Duplicate Groups',
                'message': f"{current_stats['unresolved_groups']} duplicate groups haven't been addressed yet. Review these for potential cleanup.",
                'action': 'review_unresolved',
                'icon': 'fas fa-tasks'
            })
        
        # Recommendation for partially resolved groups
        if current_stats['partially_resolved_groups'] > 0:
            recommendations.append({
                'type': 'partial_resolution',
                'priority': 'medium',
                'title': 'Partially Resolved Groups',
                'message': f"{current_stats['partially_resolved_groups']} groups have partial cleanup. Consider finishing the cleanup for these groups.",
                'action': 'complete_partial',
                'icon': 'fas fa-tasks'
            })
        
        # Recommendation for new analysis after significant cleanup
        if effectiveness['duplicates_eliminated_percentage'] > 30:
            recommendations.append({
                'type': 'new_analysis',
                'priority': 'medium',
                'title': 'Consider New Analysis',
                'message': f"You've eliminated {effectiveness['duplicates_eliminated_percentage']}% of duplicates. Running a new analysis might find additional duplicates created by recent changes.",
                'action': 'run_new_analysis',
                'icon': 'fas fa-sync-alt'
            })
        
        # Recommendation based on canonical track deletions
        if current_stats['canonical_tracks_deleted'] > 0:
            recommendations.append({
                'type': 'canonical_deleted',
                'priority': 'low',
                'title': 'Canonical Tracks Deleted',
                'message': f"{current_stats['canonical_tracks_deleted']} canonical tracks were deleted. This might indicate the duplicate detection algorithm could be improved.",
                'action': 'review_algorithm',
                'icon': 'fas fa-info-circle'
            })
        
        return recommendations
    
    def suggest_new_analysis_after_cleanup(self, analysis_id: str, 
                                         cleanup_threshold_percentage: float = 20.0) -> Dict:
        """
        Suggest running new analysis after significant cleanup based on impact analysis.
        
        Args:
            analysis_id: UUID of the analysis to check
            cleanup_threshold_percentage: Percentage of cleanup that triggers suggestion
            
        Returns:
            Dictionary with suggestion information and reasoning
        """
        try:
            impact_summary = self.get_impact_summary(analysis_id)
            
            suggestion = {
                'should_run_new_analysis': False,
                'confidence': 'low',
                'reasons': [],
                'benefits': [],
                'timing_recommendation': 'not_recommended',
                'estimated_new_duplicates': 0
            }
            
            effectiveness = impact_summary['cleanup_effectiveness']
            current_stats = impact_summary['current_stats']
            
            # Check if cleanup meets threshold
            duplicates_eliminated = effectiveness['duplicates_eliminated_percentage']
            groups_resolved = effectiveness['groups_resolved_percentage']
            
            if duplicates_eliminated >= cleanup_threshold_percentage:
                suggestion['should_run_new_analysis'] = True
                suggestion['reasons'].append(f"Eliminated {duplicates_eliminated}% of duplicates")
                
                if duplicates_eliminated >= 50:
                    suggestion['confidence'] = 'high'
                    suggestion['timing_recommendation'] = 'recommended'
                elif duplicates_eliminated >= 30:
                    suggestion['confidence'] = 'medium'
                    suggestion['timing_recommendation'] = 'suggested'
                else:
                    suggestion['confidence'] = 'low'
                    suggestion['timing_recommendation'] = 'optional'
            
            if groups_resolved >= cleanup_threshold_percentage:
                if not suggestion['should_run_new_analysis']:
                    suggestion['should_run_new_analysis'] = True
                suggestion['reasons'].append(f"Resolved {groups_resolved}% of duplicate groups")
            
            # Check for library changes since analysis
            analysis_result = db.session.query(DuplicateAnalysisResult)\
                .filter(DuplicateAnalysisResult.analysis_id == analysis_id)\
                .first()
            
            if analysis_result:
                library_changes = self.get_library_change_summary(analysis_result)
                if library_changes['significant_change']:
                    suggestion['should_run_new_analysis'] = True
                    suggestion['reasons'].append(f"Library changed by {library_changes['total_changes']} tracks")
                    
                    if suggestion['confidence'] == 'low':
                        suggestion['confidence'] = 'medium'
            
            # Estimate potential new duplicates
            if suggestion['should_run_new_analysis']:
                # Simple estimation based on cleanup effectiveness and library changes
                base_estimate = max(5, int(current_stats['tracks_deleted'] * 0.1))
                
                if 'library_changes' in locals() and library_changes['tracks_added'] > 0:
                    # New tracks might create new duplicates
                    base_estimate += int(library_changes['tracks_added'] * 0.05)
                
                suggestion['estimated_new_duplicates'] = base_estimate
                
                # Add benefits
                suggestion['benefits'] = [
                    "Find new duplicates created by recent library changes",
                    "Identify duplicates that became apparent after cleanup",
                    "Ensure comprehensive duplicate management",
                    f"Potentially find {suggestion['estimated_new_duplicates']}+ additional duplicates"
                ]
            
            return suggestion
            
        except Exception as e:
            raise Exception(f"Failed to suggest new analysis after cleanup: {str(e)}")
    
    def get_cleanup_history_summary(self, user_id: int, days_back: int = 30) -> Dict:
        """
        Get cleanup history and progress tracking showing duplicate management effectiveness over time.
        
        Args:
            user_id: ID of the user
            days_back: Number of days to look back for history
            
        Returns:
            Dictionary with cleanup history and effectiveness metrics
        """
        try:
            # Get analyses from the specified time period
            cutoff_date = datetime.now() - timedelta(days=days_back)
            
            analyses = db.session.query(DuplicateAnalysisResult)\
                .filter(DuplicateAnalysisResult.user_id == user_id)\
                .filter(DuplicateAnalysisResult.created_at >= cutoff_date)\
                .order_by(desc(DuplicateAnalysisResult.created_at))\
                .all()
            
            if not analyses:
                return {
                    'period_days': days_back,
                    'total_analyses': 0,
                    'cleanup_summary': {},
                    'effectiveness_trends': {},
                    'recommendations': []
                }
            
            # Initialize summary
            cleanup_summary = {
                'period_days': days_back,
                'total_analyses': len(analyses),
                'total_groups_found': 0,
                'total_duplicates_found': 0,
                'total_groups_resolved': 0,
                'total_tracks_deleted': 0,
                'analyses_with_cleanup': 0,
                'average_resolution_rate': 0.0,
                'most_effective_analysis': None,
                'least_effective_analysis': None
            }
            
            # Track effectiveness over time
            effectiveness_data = []
            
            for analysis in analyses:
                impact = self.get_impact_summary(analysis.analysis_id)
                
                # Update totals
                cleanup_summary['total_groups_found'] += impact['original_stats']['total_groups']
                cleanup_summary['total_duplicates_found'] += impact['original_stats']['total_duplicates']
                cleanup_summary['total_groups_resolved'] += impact['current_stats']['resolved_groups']
                cleanup_summary['total_tracks_deleted'] += impact['current_stats']['tracks_deleted']
                
                # Track if this analysis had any cleanup
                if impact['current_stats']['tracks_deleted'] > 0:
                    cleanup_summary['analyses_with_cleanup'] += 1
                
                # Store effectiveness data
                effectiveness_record = {
                    'analysis_id': analysis.analysis_id,
                    'date': analysis.created_at,
                    'groups_resolved_percentage': impact['cleanup_effectiveness']['groups_resolved_percentage'],
                    'duplicates_eliminated_percentage': impact['cleanup_effectiveness']['duplicates_eliminated_percentage'],
                    'tracks_deleted': impact['current_stats']['tracks_deleted'],
                    'groups_found': impact['original_stats']['total_groups']
                }
                effectiveness_data.append(effectiveness_record)
            
            # Calculate average resolution rate
            if cleanup_summary['total_groups_found'] > 0:
                cleanup_summary['average_resolution_rate'] = round(
                    (cleanup_summary['total_groups_resolved'] / cleanup_summary['total_groups_found']) * 100, 1
                )
            
            # Find most and least effective analyses
            if effectiveness_data:
                most_effective = max(effectiveness_data, key=lambda x: x['groups_resolved_percentage'])
                least_effective = min(effectiveness_data, key=lambda x: x['groups_resolved_percentage'])
                
                cleanup_summary['most_effective_analysis'] = {
                    'analysis_id': most_effective['analysis_id'],
                    'date': most_effective['date'],
                    'resolution_percentage': most_effective['groups_resolved_percentage']
                }
                
                cleanup_summary['least_effective_analysis'] = {
                    'analysis_id': least_effective['analysis_id'],
                    'date': least_effective['date'],
                    'resolution_percentage': least_effective['groups_resolved_percentage']
                }
            
            # Generate effectiveness trends
            effectiveness_trends = {
                'trend_direction': 'stable',
                'improvement_rate': 0.0,
                'consistency_score': 0.0,
                'recent_performance': 'average'
            }
            
            if len(effectiveness_data) >= 3:
                # Calculate trend (simple linear regression on resolution percentages)
                recent_analyses = effectiveness_data[:3]  # Most recent 3
                older_analyses = effectiveness_data[-3:] if len(effectiveness_data) >= 6 else effectiveness_data[3:]
                
                if older_analyses:
                    recent_avg = sum(a['groups_resolved_percentage'] for a in recent_analyses) / len(recent_analyses)
                    older_avg = sum(a['groups_resolved_percentage'] for a in older_analyses) / len(older_analyses)
                    
                    improvement_rate = recent_avg - older_avg
                    effectiveness_trends['improvement_rate'] = round(improvement_rate, 1)
                    
                    if improvement_rate > 10:
                        effectiveness_trends['trend_direction'] = 'improving'
                        effectiveness_trends['recent_performance'] = 'excellent'
                    elif improvement_rate > 5:
                        effectiveness_trends['trend_direction'] = 'improving'
                        effectiveness_trends['recent_performance'] = 'good'
                    elif improvement_rate < -10:
                        effectiveness_trends['trend_direction'] = 'declining'
                        effectiveness_trends['recent_performance'] = 'poor'
                    elif improvement_rate < -5:
                        effectiveness_trends['trend_direction'] = 'declining'
                        effectiveness_trends['recent_performance'] = 'below_average'
                
                # Calculate consistency (standard deviation of resolution rates)
                resolution_rates = [a['groups_resolved_percentage'] for a in effectiveness_data]
                if len(resolution_rates) > 1:
                    mean_rate = sum(resolution_rates) / len(resolution_rates)
                    variance = sum((rate - mean_rate) ** 2 for rate in resolution_rates) / len(resolution_rates)
                    std_dev = variance ** 0.5
                    
                    # Convert to consistency score (lower std dev = higher consistency)
                    effectiveness_trends['consistency_score'] = round(max(0, 100 - std_dev), 1)
            
            # Generate recommendations based on history
            recommendations = self._generate_history_based_recommendations(
                cleanup_summary, effectiveness_trends, effectiveness_data
            )
            
            return {
                'cleanup_summary': cleanup_summary,
                'effectiveness_trends': effectiveness_trends,
                'effectiveness_data': effectiveness_data,
                'recommendations': recommendations
            }
            
        except Exception as e:
            raise Exception(f"Failed to get cleanup history summary: {str(e)}")
    
    def _generate_history_based_recommendations(self, cleanup_summary: Dict, 
                                              effectiveness_trends: Dict, 
                                              effectiveness_data: List[Dict]) -> List[Dict]:
        """
        Generate recommendations for additional cleanup based on resolution patterns and history.
        
        Args:
            cleanup_summary: Summary of cleanup activities
            effectiveness_trends: Trend analysis data
            effectiveness_data: Individual analysis effectiveness records
            
        Returns:
            List of recommendation dictionaries
        """
        recommendations = []
        
        # Recommendation based on overall effectiveness
        avg_resolution = cleanup_summary['average_resolution_rate']
        if avg_resolution < 30:
            recommendations.append({
                'type': 'low_effectiveness',
                'priority': 'high',
                'title': 'Low Cleanup Effectiveness',
                'message': f"Your average resolution rate is {avg_resolution}%. Consider reviewing your cleanup strategy or running more frequent analyses.",
                'action': 'improve_strategy',
                'icon': 'fas fa-exclamation-triangle'
            })
        elif avg_resolution < 60:
            recommendations.append({
                'type': 'moderate_effectiveness',
                'priority': 'medium',
                'title': 'Moderate Cleanup Effectiveness',
                'message': f"Your average resolution rate is {avg_resolution}%. There's room for improvement in your duplicate management.",
                'action': 'optimize_workflow',
                'icon': 'fas fa-chart-line'
            })
        
        # Recommendation based on trend
        if effectiveness_trends['trend_direction'] == 'declining':
            recommendations.append({
                'type': 'declining_performance',
                'priority': 'high',
                'title': 'Declining Cleanup Performance',
                'message': f"Your cleanup effectiveness has declined by {abs(effectiveness_trends['improvement_rate'])}% recently. Consider reviewing your approach.",
                'action': 'review_approach',
                'icon': 'fas fa-arrow-down'
            })
        elif effectiveness_trends['trend_direction'] == 'improving':
            recommendations.append({
                'type': 'improving_performance',
                'priority': 'low',
                'title': 'Improving Cleanup Performance',
                'message': f"Great! Your cleanup effectiveness has improved by {effectiveness_trends['improvement_rate']}% recently.",
                'action': 'maintain_momentum',
                'icon': 'fas fa-arrow-up'
            })
        
        # Recommendation based on consistency
        if effectiveness_trends['consistency_score'] < 50:
            recommendations.append({
                'type': 'inconsistent_performance',
                'priority': 'medium',
                'title': 'Inconsistent Cleanup Performance',
                'message': "Your cleanup effectiveness varies significantly between analyses. Consider developing a more systematic approach.",
                'action': 'standardize_approach',
                'icon': 'fas fa-balance-scale'
            })
        
        # Recommendation based on activity level
        analyses_with_cleanup = cleanup_summary['analyses_with_cleanup']
        total_analyses = cleanup_summary['total_analyses']
        
        if total_analyses > 0 and (analyses_with_cleanup / total_analyses) < 0.5:
            recommendations.append({
                'type': 'low_activity',
                'priority': 'medium',
                'title': 'Low Cleanup Activity',
                'message': f"Only {analyses_with_cleanup} of {total_analyses} recent analyses resulted in cleanup. Consider being more proactive with duplicate management.",
                'action': 'increase_activity',
                'icon': 'fas fa-clock'
            })
        
        # Recommendation for regular analysis
        if len(effectiveness_data) > 0:
            most_recent = effectiveness_data[0]['date']
            days_since_last = (datetime.now() - most_recent).days
            
            if days_since_last > 14:
                recommendations.append({
                    'type': 'stale_analysis',
                    'priority': 'medium',
                    'title': 'Time for New Analysis',
                    'message': f"It's been {days_since_last} days since your last analysis. Consider running a new duplicate detection.",
                    'action': 'run_new_analysis',
                    'icon': 'fas fa-calendar-alt'
                })
        
        return recommendations
    
    # ============================================================================
    # Cleanup History and Progress Tracking (Sub-task 8.2)
    # ============================================================================
    
    def log_cleanup_action(self, action_type: str, operation_type: str, user_id: int,
                          analysis_id: Optional[str] = None, 
                          affected_track_ids: Optional[List[int]] = None,
                          affected_group_ids: Optional[List[int]] = None,
                          resolution_action: Optional[str] = None,
                          cleanup_strategy: Optional[str] = None,
                          processing_time_seconds: Optional[float] = None,
                          context_data: Optional[Dict] = None,
                          success: bool = True,
                          error_message: Optional[str] = None) -> str:
        """
        Create cleanup action audit trail with timestamps and user information.
        
        Args:
            action_type: Type of action ('track_deleted', 'group_resolved', 'bulk_cleanup', 'analysis_refresh')
            operation_type: Type of operation ('single_delete', 'bulk_delete', 'smart_delete', 'manual_resolution')
            user_id: ID of the user performing the action
            analysis_id: Optional analysis ID if action is related to specific analysis
            affected_track_ids: List of track IDs affected by the action
            affected_group_ids: List of group IDs affected by the action
            resolution_action: Resolution action taken
            cleanup_strategy: Strategy used for cleanup
            processing_time_seconds: Time taken to process the action
            context_data: Additional context information
            success: Whether the action was successful
            error_message: Error message if action failed
            
        Returns:
            Action ID (UUID) for grouping related actions
        """
        try:
            from models import DuplicateCleanupAuditLog
            import uuid
            
            # Generate action ID for grouping related actions
            action_id = str(uuid.uuid4())
            
            # Calculate metrics
            tracks_deleted_count = len(affected_track_ids) if affected_track_ids else 0
            groups_resolved_count = len(affected_group_ids) if affected_group_ids else 0
            
            # Calculate total play count affected
            total_play_count_affected = 0
            if affected_track_ids:
                from models import Track
                tracks = db.session.query(Track).filter(Track.id.in_(affected_track_ids)).all()
                total_play_count_affected = sum(track.play_cnt or 0 for track in tracks)
            
            # Create audit log entry
            audit_log = DuplicateCleanupAuditLog(
                action_id=action_id,
                analysis_id=analysis_id,
                user_id=user_id,
                timestamp=datetime.now(),
                action_type=action_type,
                operation_type=operation_type,
                affected_track_ids=affected_track_ids,
                affected_group_ids=affected_group_ids,
                tracks_deleted_count=tracks_deleted_count,
                groups_resolved_count=groups_resolved_count,
                resolution_action=resolution_action,
                cleanup_strategy=cleanup_strategy,
                processing_time_seconds=processing_time_seconds,
                total_play_count_affected=total_play_count_affected,
                context_data=context_data,
                success=success,
                error_message=error_message
            )
            
            db.session.add(audit_log)
            db.session.commit()
            
            return action_id
            
        except Exception as e:
            db.session.rollback()
            raise Exception(f"Failed to log cleanup action: {str(e)}")
    
    def get_cleanup_audit_trail(self, user_id: int, days_back: int = 30, 
                               analysis_id: Optional[str] = None,
                               action_type: Optional[str] = None) -> List[Dict]:
        """
        Get cleanup action audit trail with timestamps and user information.
        
        Args:
            user_id: ID of the user
            days_back: Number of days to look back
            analysis_id: Optional filter by specific analysis
            action_type: Optional filter by action type
            
        Returns:
            List of audit trail entries with detailed information
        """
        try:
            from models import DuplicateCleanupAuditLog
            
            # Build query
            cutoff_date = datetime.now() - timedelta(days=days_back)
            
            query = db.session.query(DuplicateCleanupAuditLog)\
                .filter(DuplicateCleanupAuditLog.user_id == user_id)\
                .filter(DuplicateCleanupAuditLog.timestamp >= cutoff_date)
            
            if analysis_id:
                query = query.filter(DuplicateCleanupAuditLog.analysis_id == analysis_id)
            
            if action_type:
                query = query.filter(DuplicateCleanupAuditLog.action_type == action_type)
            
            audit_entries = query.order_by(desc(DuplicateCleanupAuditLog.timestamp)).all()
            
            # Convert to dictionaries with additional formatting
            audit_trail = []
            for entry in audit_entries:
                audit_data = {
                    'action_id': entry.action_id,
                    'analysis_id': entry.analysis_id,
                    'timestamp': entry.timestamp,
                    'timestamp_formatted': entry.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    'action_type': entry.action_type,
                    'operation_type': entry.operation_type,
                    'tracks_deleted_count': entry.tracks_deleted_count,
                    'groups_resolved_count': entry.groups_resolved_count,
                    'resolution_action': entry.resolution_action,
                    'cleanup_strategy': entry.cleanup_strategy,
                    'processing_time_seconds': entry.processing_time_seconds,
                    'total_play_count_affected': entry.total_play_count_affected,
                    'success': entry.success,
                    'error_message': entry.error_message,
                    'context_data': entry.context_data,
                    'affected_track_count': len(entry.affected_track_ids) if entry.affected_track_ids else 0,
                    'affected_group_count': len(entry.affected_group_ids) if entry.affected_group_ids else 0
                }
                
                # Add human-readable descriptions
                audit_data['description'] = self._generate_audit_description(entry)
                audit_data['impact_summary'] = self._generate_audit_impact_summary(entry)
                
                audit_trail.append(audit_data)
            
            return audit_trail
            
        except Exception as e:
            raise Exception(f"Failed to get cleanup audit trail: {str(e)}")
    
    def _generate_audit_description(self, audit_entry) -> str:
        """Generate human-readable description for audit entry."""
        action_descriptions = {
            'track_deleted': 'Deleted duplicate track(s)',
            'group_resolved': 'Resolved duplicate group(s)',
            'bulk_cleanup': 'Performed bulk cleanup operation',
            'analysis_refresh': 'Refreshed duplicate analysis'
        }
        
        operation_descriptions = {
            'single_delete': 'individual deletion',
            'bulk_delete': 'bulk deletion',
            'smart_delete': 'smart deletion algorithm',
            'manual_resolution': 'manual resolution'
        }
        
        base_description = action_descriptions.get(audit_entry.action_type, audit_entry.action_type)
        operation_detail = operation_descriptions.get(audit_entry.operation_type, audit_entry.operation_type)
        
        if audit_entry.tracks_deleted_count > 0:
            return f"{base_description} ({audit_entry.tracks_deleted_count} tracks) via {operation_detail}"
        elif audit_entry.groups_resolved_count > 0:
            return f"{base_description} ({audit_entry.groups_resolved_count} groups) via {operation_detail}"
        else:
            return f"{base_description} via {operation_detail}"
    
    def _generate_audit_impact_summary(self, audit_entry) -> Dict:
        """Generate impact summary for audit entry."""
        return {
            'tracks_affected': audit_entry.tracks_deleted_count,
            'groups_affected': audit_entry.groups_resolved_count,
            'play_count_impact': audit_entry.total_play_count_affected,
            'processing_time': audit_entry.processing_time_seconds,
            'efficiency_score': self._calculate_efficiency_score(audit_entry)
        }
    
    def _calculate_efficiency_score(self, audit_entry) -> float:
        """Calculate efficiency score for cleanup action (0-100)."""
        if not audit_entry.processing_time_seconds or audit_entry.processing_time_seconds <= 0:
            return 100.0
        
        # Base score on tracks processed per second
        tracks_per_second = audit_entry.tracks_deleted_count / audit_entry.processing_time_seconds
        
        # Normalize to 0-100 scale (assuming 1 track/second is average)
        efficiency_score = min(100.0, tracks_per_second * 100)
        
        return round(efficiency_score, 1)
    
    def get_duplicate_management_effectiveness_stats(self, user_id: int, 
                                                   days_back: int = 90) -> Dict:
        """
        Add summary statistics showing duplicate management effectiveness over time.
        
        Args:
            user_id: ID of the user
            days_back: Number of days to analyze
            
        Returns:
            Dictionary with comprehensive effectiveness statistics
        """
        try:
            from models import DuplicateCleanupAuditLog
            
            cutoff_date = datetime.now() - timedelta(days=days_back)
            
            # Get all cleanup actions in the time period
            cleanup_actions = db.session.query(DuplicateCleanupAuditLog)\
                .filter(DuplicateCleanupAuditLog.user_id == user_id)\
                .filter(DuplicateCleanupAuditLog.timestamp >= cutoff_date)\
                .order_by(DuplicateCleanupAuditLog.timestamp)\
                .all()
            
            if not cleanup_actions:
                return {
                    'period_days': days_back,
                    'total_actions': 0,
                    'effectiveness_metrics': {},
                    'trend_analysis': {},
                    'performance_insights': []
                }
            
            # Calculate overall statistics
            total_actions = len(cleanup_actions)
            total_tracks_deleted = sum(action.tracks_deleted_count for action in cleanup_actions)
            total_groups_resolved = sum(action.groups_resolved_count for action in cleanup_actions)
            total_play_count_affected = sum(action.total_play_count_affected for action in cleanup_actions)
            successful_actions = sum(1 for action in cleanup_actions if action.success)
            
            # Calculate time-based metrics
            total_processing_time = sum(action.processing_time_seconds or 0 for action in cleanup_actions)
            average_processing_time = total_processing_time / total_actions if total_actions > 0 else 0
            
            # Group actions by week for trend analysis
            weekly_stats = {}
            for action in cleanup_actions:
                week_start = action.timestamp - timedelta(days=action.timestamp.weekday())
                week_key = week_start.strftime('%Y-%W')
                
                if week_key not in weekly_stats:
                    weekly_stats[week_key] = {
                        'week_start': week_start,
                        'actions': 0,
                        'tracks_deleted': 0,
                        'groups_resolved': 0,
                        'processing_time': 0
                    }
                
                weekly_stats[week_key]['actions'] += 1
                weekly_stats[week_key]['tracks_deleted'] += action.tracks_deleted_count
                weekly_stats[week_key]['groups_resolved'] += action.groups_resolved_count
                weekly_stats[week_key]['processing_time'] += action.processing_time_seconds or 0
            
            # Calculate effectiveness metrics
            effectiveness_metrics = {
                'total_actions': total_actions,
                'total_tracks_deleted': total_tracks_deleted,
                'total_groups_resolved': total_groups_resolved,
                'total_play_count_affected': total_play_count_affected,
                'success_rate': (successful_actions / total_actions) * 100 if total_actions > 0 else 0,
                'average_tracks_per_action': total_tracks_deleted / total_actions if total_actions > 0 else 0,
                'average_groups_per_action': total_groups_resolved / total_actions if total_actions > 0 else 0,
                'average_processing_time': average_processing_time,
                'tracks_per_second': total_tracks_deleted / total_processing_time if total_processing_time > 0 else 0,
                'actions_per_week': total_actions / (days_back / 7) if days_back > 0 else 0
            }
            
            # Analyze trends
            weekly_data = list(weekly_stats.values())
            trend_analysis = {
                'weekly_activity': len(weekly_data),
                'most_active_week': None,
                'least_active_week': None,
                'activity_trend': 'stable',
                'efficiency_trend': 'stable'
            }
            
            if weekly_data:
                # Find most and least active weeks
                most_active = max(weekly_data, key=lambda w: w['tracks_deleted'])
                least_active = min(weekly_data, key=lambda w: w['tracks_deleted'])
                
                trend_analysis['most_active_week'] = {
                    'week_start': most_active['week_start'].strftime('%Y-%m-%d'),
                    'tracks_deleted': most_active['tracks_deleted'],
                    'actions': most_active['actions']
                }
                
                trend_analysis['least_active_week'] = {
                    'week_start': least_active['week_start'].strftime('%Y-%m-%d'),
                    'tracks_deleted': least_active['tracks_deleted'],
                    'actions': least_active['actions']
                }
                
                # Calculate activity trend (simple linear regression)
                if len(weekly_data) >= 3:
                    recent_weeks = weekly_data[-3:]
                    older_weeks = weekly_data[:3] if len(weekly_data) >= 6 else weekly_data[:-3]
                    
                    if older_weeks:
                        recent_avg = sum(w['tracks_deleted'] for w in recent_weeks) / len(recent_weeks)
                        older_avg = sum(w['tracks_deleted'] for w in older_weeks) / len(older_weeks)
                        
                        if recent_avg > older_avg * 1.2:
                            trend_analysis['activity_trend'] = 'increasing'
                        elif recent_avg < older_avg * 0.8:
                            trend_analysis['activity_trend'] = 'decreasing'
            
            # Generate performance insights
            performance_insights = self._generate_effectiveness_insights(
                effectiveness_metrics, trend_analysis, cleanup_actions
            )
            
            return {
                'period_days': days_back,
                'effectiveness_metrics': effectiveness_metrics,
                'trend_analysis': trend_analysis,
                'weekly_stats': weekly_stats,
                'performance_insights': performance_insights
            }
            
        except Exception as e:
            raise Exception(f"Failed to get duplicate management effectiveness stats: {str(e)}")
    
    def _generate_effectiveness_insights(self, metrics: Dict, trends: Dict, 
                                       cleanup_actions: List) -> List[Dict]:
        """
        Generate performance insights based on effectiveness statistics.
        
        Args:
            metrics: Effectiveness metrics
            trends: Trend analysis data
            cleanup_actions: List of cleanup actions
            
        Returns:
            List of insight dictionaries
        """
        insights = []
        
        # Success rate insights
        success_rate = metrics['success_rate']
        if success_rate < 90:
            insights.append({
                'type': 'success_rate',
                'priority': 'high' if success_rate < 80 else 'medium',
                'title': 'Low Success Rate',
                'message': f"Your cleanup success rate is {success_rate:.1f}%. Consider reviewing error patterns.",
                'recommendation': 'Check error logs and improve cleanup strategies',
                'icon': 'fas fa-exclamation-triangle'
            })
        elif success_rate >= 95:
            insights.append({
                'type': 'success_rate',
                'priority': 'low',
                'title': 'Excellent Success Rate',
                'message': f"Outstanding! Your cleanup success rate is {success_rate:.1f}%.",
                'recommendation': 'Keep up the excellent work',
                'icon': 'fas fa-check-circle'
            })
        
        # Efficiency insights
        tracks_per_second = metrics['tracks_per_second']
        if tracks_per_second < 0.5:
            insights.append({
                'type': 'efficiency',
                'priority': 'medium',
                'title': 'Slow Processing Speed',
                'message': f"Processing {tracks_per_second:.2f} tracks per second. Consider optimizing your approach.",
                'recommendation': 'Use bulk operations and smart deletion algorithms',
                'icon': 'fas fa-clock'
            })
        elif tracks_per_second > 2.0:
            insights.append({
                'type': 'efficiency',
                'priority': 'low',
                'title': 'High Processing Efficiency',
                'message': f"Excellent processing speed: {tracks_per_second:.2f} tracks per second.",
                'recommendation': 'Your cleanup workflow is highly optimized',
                'icon': 'fas fa-tachometer-alt'
            })
        
        # Activity level insights
        actions_per_week = metrics['actions_per_week']
        if actions_per_week < 1:
            insights.append({
                'type': 'activity',
                'priority': 'medium',
                'title': 'Low Activity Level',
                'message': f"Only {actions_per_week:.1f} cleanup actions per week. Consider more regular maintenance.",
                'recommendation': 'Schedule regular duplicate cleanup sessions',
                'icon': 'fas fa-calendar-alt'
            })
        elif actions_per_week > 5:
            insights.append({
                'type': 'activity',
                'priority': 'low',
                'title': 'High Activity Level',
                'message': f"Very active with {actions_per_week:.1f} cleanup actions per week.",
                'recommendation': 'Consider automating some cleanup tasks',
                'icon': 'fas fa-chart-line'
            })
        
        # Trend insights
        if trends['activity_trend'] == 'increasing':
            insights.append({
                'type': 'trend',
                'priority': 'low',
                'title': 'Increasing Activity',
                'message': "Your cleanup activity has been increasing recently.",
                'recommendation': 'Great momentum! Keep up the regular maintenance',
                'icon': 'fas fa-arrow-up'
            })
        elif trends['activity_trend'] == 'decreasing':
            insights.append({
                'type': 'trend',
                'priority': 'medium',
                'title': 'Decreasing Activity',
                'message': "Your cleanup activity has been decreasing recently.",
                'recommendation': 'Consider setting up regular cleanup reminders',
                'icon': 'fas fa-arrow-down'
            })
        
        return insights
    
    def get_cleanup_recommendations_based_on_patterns(self, user_id: int, 
                                                    days_back: int = 30) -> List[Dict]:
        """
        Create recommendations for additional cleanup based on resolution patterns.
        
        Args:
            user_id: ID of the user
            days_back: Number of days to analyze for patterns
            
        Returns:
            List of recommendation dictionaries based on cleanup patterns
        """
        try:
            from models import DuplicateCleanupAuditLog
            
            # Get recent cleanup actions
            cutoff_date = datetime.now() - timedelta(days=days_back)
            
            cleanup_actions = db.session.query(DuplicateCleanupAuditLog)\
                .filter(DuplicateCleanupAuditLog.user_id == user_id)\
                .filter(DuplicateCleanupAuditLog.timestamp >= cutoff_date)\
                .order_by(desc(DuplicateCleanupAuditLog.timestamp))\
                .all()
            
            if not cleanup_actions:
                return [{
                    'type': 'no_activity',
                    'priority': 'medium',
                    'title': 'No Recent Cleanup Activity',
                    'message': f"No cleanup actions found in the last {days_back} days.",
                    'recommendation': 'Run a duplicate analysis to identify cleanup opportunities',
                    'action': 'run_analysis',
                    'icon': 'fas fa-search'
                }]
            
            recommendations = []
            
            # Analyze cleanup patterns
            action_types = {}
            operation_types = {}
            resolution_actions = {}
            
            for action in cleanup_actions:
                action_types[action.action_type] = action_types.get(action.action_type, 0) + 1
                operation_types[action.operation_type] = operation_types.get(action.operation_type, 0) + 1
                if action.resolution_action:
                    resolution_actions[action.resolution_action] = resolution_actions.get(action.resolution_action, 0) + 1
            
            # Pattern-based recommendations
            
            # 1. If user mostly does single deletions, suggest bulk operations
            if operation_types.get('single_delete', 0) > operation_types.get('bulk_delete', 0) * 3:
                recommendations.append({
                    'type': 'operation_efficiency',
                    'priority': 'medium',
                    'title': 'Consider Bulk Operations',
                    'message': 'You mostly perform single deletions. Bulk operations could be more efficient.',
                    'recommendation': 'Try using bulk delete or smart delete features for similar duplicates',
                    'action': 'use_bulk_operations',
                    'icon': 'fas fa-layer-group'
                })
            
            # 2. If many canonical tracks are being deleted, suggest algorithm review
            canonical_deletions = resolution_actions.get('canonical_deleted', 0)
            total_resolutions = sum(resolution_actions.values())
            
            if total_resolutions > 0 and (canonical_deletions / total_resolutions) > 0.3:
                recommendations.append({
                    'type': 'algorithm_accuracy',
                    'priority': 'high',
                    'title': 'High Canonical Track Deletions',
                    'message': f'{canonical_deletions} canonical tracks deleted. The duplicate detection algorithm might need tuning.',
                    'recommendation': 'Review duplicate detection settings or provide feedback on incorrect canonical selections',
                    'action': 'review_algorithm',
                    'icon': 'fas fa-cog'
                })
            
            # 3. If processing time is consistently high, suggest optimization
            avg_processing_time = sum(action.processing_time_seconds or 0 for action in cleanup_actions) / len(cleanup_actions)
            if avg_processing_time > 5.0:  # More than 5 seconds average
                recommendations.append({
                    'type': 'performance_optimization',
                    'priority': 'medium',
                    'title': 'Slow Processing Times',
                    'message': f'Average processing time is {avg_processing_time:.1f} seconds per action.',
                    'recommendation': 'Consider using smart deletion algorithms or processing smaller batches',
                    'action': 'optimize_performance',
                    'icon': 'fas fa-tachometer-alt'
                })
            
            # 4. If there are many failed actions, suggest troubleshooting
            failed_actions = sum(1 for action in cleanup_actions if not action.success)
            if failed_actions > len(cleanup_actions) * 0.1:  # More than 10% failure rate
                recommendations.append({
                    'type': 'error_rate',
                    'priority': 'high',
                    'title': 'High Failure Rate',
                    'message': f'{failed_actions} out of {len(cleanup_actions)} actions failed.',
                    'recommendation': 'Review error logs and check for common failure patterns',
                    'action': 'troubleshoot_errors',
                    'icon': 'fas fa-exclamation-triangle'
                })
            
            # 5. If user hasn't done cleanup recently, suggest maintenance
            most_recent_action = max(cleanup_actions, key=lambda a: a.timestamp)
            days_since_last = (datetime.now() - most_recent_action.timestamp).days
            
            if days_since_last > 7:
                recommendations.append({
                    'type': 'maintenance_schedule',
                    'priority': 'low',
                    'title': 'Regular Maintenance Reminder',
                    'message': f'Last cleanup was {days_since_last} days ago.',
                    'recommendation': 'Consider setting up a regular cleanup schedule (weekly or bi-weekly)',
                    'action': 'schedule_maintenance',
                    'icon': 'fas fa-calendar-check'
                })
            
            # 6. If user has been very active, suggest analysis refresh
            if len(cleanup_actions) > 20:  # Very active
                recommendations.append({
                    'type': 'analysis_refresh',
                    'priority': 'medium',
                    'title': 'Consider Analysis Refresh',
                    'message': f'You\'ve performed {len(cleanup_actions)} cleanup actions recently.',
                    'recommendation': 'Run a new duplicate analysis to find additional duplicates created by recent changes',
                    'action': 'refresh_analysis',
                    'icon': 'fas fa-sync-alt'
                })
            
            return recommendations
            
        except Exception as e:
            raise Exception(f"Failed to get cleanup recommendations based on patterns: {str(e)}")
    
    def get_export_progress(self, export_id: str) -> Dict:
        """
        Get export progress for large datasets (placeholder for future implementation).
        
        Args:
            export_id: UUID of the export operation
            
        Returns:
            Dictionary with progress information
        """
        # This is a placeholder for future implementation of async exports
        # For now, exports are synchronous
        return {
            'export_id': export_id,
            'status': 'completed',
            'progress_percentage': 100,
            'message': 'Export completed'
        }
    
    def get_export_history(self, user_id: int, analysis_id: Optional[str] = None, 
                          limit: int = 10, offset: int = 0) -> List[DuplicateAnalysisExport]:
        """
        Get export history tracking with file size and format information.
        
        Args:
            user_id: ID of the user
            analysis_id: Optional analysis ID to filter exports
            limit: Maximum number of results to return
            offset: Number of results to skip (for pagination)
            
        Returns:
            List of DuplicateAnalysisExport objects ordered by creation date (newest first)
        """
        try:
            query = db.session.query(DuplicateAnalysisExport)\
                .filter(DuplicateAnalysisExport.user_id == user_id)\
                .filter(DuplicateAnalysisExport.status == 'completed')
            
            # Filter by analysis ID if provided
            if analysis_id:
                query = query.filter(DuplicateAnalysisExport.analysis_id == analysis_id)
            
            exports = query.order_by(desc(DuplicateAnalysisExport.created_at))\
                .limit(limit)\
                .offset(offset)\
                .all()
            
            return exports
            
        except Exception as e:
            raise Exception(f"Failed to get export history: {str(e)}")
    
    def get_export_by_id(self, export_id: str, user_id: Optional[int] = None) -> Optional[DuplicateAnalysisExport]:
        """
        Get export record by ID with optional user authorization check.
        
        Args:
            export_id: UUID of the export
            user_id: Optional user ID for security check
            
        Returns:
            DuplicateAnalysisExport object or None if not found
        """
        try:
            query = db.session.query(DuplicateAnalysisExport)\
                .filter(DuplicateAnalysisExport.export_id == export_id)
            
            # Add user security check if provided
            if user_id:
                query = query.filter(DuplicateAnalysisExport.user_id == user_id)
            
            return query.first()
            
        except Exception as e:
            raise Exception(f"Failed to get export by ID: {str(e)}")
    
    def mark_export_downloaded(self, export_id: str, user_id: Optional[int] = None) -> bool:
        """
        Mark export as downloaded and update download statistics.
        
        Args:
            export_id: UUID of the export
            user_id: Optional user ID for security check
            
        Returns:
            True if updated successfully, False if not found
        """
        try:
            query = db.session.query(DuplicateAnalysisExport)\
                .filter(DuplicateAnalysisExport.export_id == export_id)
            
            # Add user security check if provided
            if user_id:
                query = query.filter(DuplicateAnalysisExport.user_id == user_id)
            
            export_record = query.first()
            
            if not export_record:
                return False
            
            # Update download statistics
            export_record.download_count += 1
            export_record.last_downloaded_at = datetime.now()
            
            db.session.commit()
            return True
            
        except Exception as e:
            db.session.rollback()
            raise Exception(f"Failed to mark export as downloaded: {str(e)}")
    
    def cleanup_expired_exports(self) -> Dict[str, int]:
        """
        Clean up expired export files and database records.
        
        Returns:
            Dictionary with cleanup statistics
        """
        try:
            cleanup_stats = {
                'files_deleted': 0,
                'records_deleted': 0,
                'errors': 0
            }
            
            # Find expired exports
            expired_exports = db.session.query(DuplicateAnalysisExport)\
                .filter(
                    and_(
                        DuplicateAnalysisExport.expires_at < datetime.now(),
                        DuplicateAnalysisExport.status == 'completed'
                    )
                )\
                .all()
            
            for export in expired_exports:
                try:
                    # Delete file if it exists
                    if export.file_path and os.path.exists(export.file_path):
                        os.remove(export.file_path)
                        cleanup_stats['files_deleted'] += 1
                    
                    # Update record status
                    export.status = 'expired'
                    cleanup_stats['records_deleted'] += 1
                    
                except Exception as e:
                    cleanup_stats['errors'] += 1
                    print(f"Error cleaning up export {export.export_id}: {str(e)}")
            
            # Commit changes
            db.session.commit()
            
            return cleanup_stats
            
        except Exception as e:
            db.session.rollback()
            raise Exception(f"Failed to cleanup expired exports: {str(e)}")
    
    def delete_export(self, export_id: str, user_id: Optional[int] = None) -> bool:
        """
        Delete an export record and its associated file.
        
        Args:
            export_id: UUID of the export to delete
            user_id: Optional user ID for security check
            
        Returns:
            True if deleted successfully, False if not found
        """
        try:
            query = db.session.query(DuplicateAnalysisExport)\
                .filter(DuplicateAnalysisExport.export_id == export_id)
            
            # Add user security check if provided
            if user_id:
                query = query.filter(DuplicateAnalysisExport.user_id == user_id)
            
            export_record = query.first()
            
            if not export_record:
                return False
            
            # Delete file if it exists
            if export_record.file_path and os.path.exists(export_record.file_path):
                try:
                    os.remove(export_record.file_path)
                except Exception as e:
                    print(f"Warning: Failed to delete export file {export_record.file_path}: {str(e)}")
            
            # Delete database record
            db.session.delete(export_record)
            db.session.commit()
            
            return True
            
        except Exception as e:
            db.session.rollback()
            raise Exception(f"Failed to delete export: {str(e)}")
    
    def get_export_statistics(self, user_id: int, days: int = 30) -> Dict:
        """
        Get export usage statistics for a user.
        
        Args:
            user_id: ID of the user
            days: Number of days to look back for statistics
            
        Returns:
            Dictionary with export statistics
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            
            # Get export counts by format
            format_stats = db.session.query(
                DuplicateAnalysisExport.format,
                func.count(DuplicateAnalysisExport.id).label('count'),
                func.sum(DuplicateAnalysisExport.file_size).label('total_size'),
                func.sum(DuplicateAnalysisExport.download_count).label('total_downloads')
            )\
            .filter(
                and_(
                    DuplicateAnalysisExport.user_id == user_id,
                    DuplicateAnalysisExport.created_at >= cutoff_date
                )
            )\
            .group_by(DuplicateAnalysisExport.format)\
            .all()
            
            # Get total statistics
            total_stats = db.session.query(
                func.count(DuplicateAnalysisExport.id).label('total_exports'),
                func.sum(DuplicateAnalysisExport.file_size).label('total_size'),
                func.sum(DuplicateAnalysisExport.download_count).label('total_downloads')
            )\
            .filter(
                and_(
                    DuplicateAnalysisExport.user_id == user_id,
                    DuplicateAnalysisExport.created_at >= cutoff_date
                )
            )\
            .first()
            
            # Format results
            format_breakdown = {}
            for format_name, count, total_size, total_downloads in format_stats:
                format_breakdown[format_name] = {
                    'count': count,
                    'total_size': total_size or 0,
                    'total_size_mb': round((total_size or 0) / (1024 * 1024), 2),
                    'total_downloads': total_downloads or 0
                }
            
            return {
                'period_days': days,
                'total_exports': total_stats.total_exports or 0,
                'total_size': total_stats.total_size or 0,
                'total_size_mb': round((total_stats.total_size or 0) / (1024 * 1024), 2),
                'total_downloads': total_stats.total_downloads or 0,
                'format_breakdown': format_breakdown
            }
            
        except Exception as e:
            raise Exception(f"Failed to get export statistics: {str(e)}")


def get_duplicate_persistence_service() -> DuplicatePersistenceService:
    """
    Factory function to get a DuplicatePersistenceService instance.
    
    Returns:
        DuplicatePersistenceService instance
    """
    return DuplicatePersistenceService()