# services/playlist_versioning_service.py
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import and_, or_, desc, func
from sqlalchemy.exc import SQLAlchemyError
from flask import current_app
from models import db, Playlist, PlaylistVersion, PlaylistVersionTrack

logger = logging.getLogger(__name__)

# Simple in-memory cache for frequently accessed versions
_version_cache = {}
_cache_ttl = 300  # 5 minutes


class PlaylistVersioningService:
    """
    Service class for managing playlist versions and temporal correlation.
    Provides methods to create, query, and manage playlist version snapshots.
    """
    
    @staticmethod
    def create_version_from_current_playlist(playlist_name: str, username: str = None) -> Optional[str]:
        """
        Create a versioned snapshot of the current playlist before it gets replaced.
        
        Args:
            playlist_name: Name of the playlist to version
            username: Username associated with the playlist
            
        Returns:
            version_id: Unique identifier for the created version, or None if failed
        """
        try:
            # Query current playlist data
            current_playlist = db.session.query(Playlist).filter(
                and_(
                    Playlist.playlist_name == playlist_name,
                    Playlist.username == username if username else True
                )
            ).order_by(Playlist.track_position).all()
            
            if not current_playlist:
                logger.info(f"No current playlist found for '{playlist_name}' (username: {username})")
                return None
            
            # Generate unique version ID
            version_id = str(uuid.uuid4())
            current_time = datetime.utcnow()
            
            # Determine when this playlist became active (use the playlist_date from first track)
            active_from = current_playlist[0].playlist_date if current_playlist else current_time
            
            # Mark any existing active version as inactive
            existing_active = db.session.query(PlaylistVersion).filter(
                and_(
                    PlaylistVersion.playlist_name == playlist_name,
                    PlaylistVersion.username == username if username else True,
                    PlaylistVersion.active_until.is_(None)
                )
            ).first()
            
            if existing_active:
                existing_active.active_until = current_time
                logger.info(f"Marked existing version {existing_active.version_id} as inactive")
            
            # Create new playlist version record
            playlist_version = PlaylistVersion(
                version_id=version_id,
                playlist_name=playlist_name,
                created_at=current_time,
                active_from=active_from,
                active_until=None,  # This will be the new active version
                track_count=len(current_playlist),
                username=username
            )
            
            db.session.add(playlist_version)
            
            # Create version track records
            version_tracks = []
            for track in current_playlist:
                version_track = PlaylistVersionTrack(
                    version_id=version_id,
                    track_position=track.track_position,
                    artist=track.artist,
                    song=track.song,
                    category=track.category,
                    play_cnt=track.play_cnt,
                    artist_common_name=track.artist_common_name
                )
                version_tracks.append(version_track)
            
            db.session.add_all(version_tracks)
            db.session.commit()
            
            logger.info(f"Created playlist version {version_id} for '{playlist_name}' with {len(version_tracks)} tracks")
            return version_id
            
        except SQLAlchemyError as e:
            logger.error(f"Database error creating playlist version for '{playlist_name}': {str(e)}")
            db.session.rollback()
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating playlist version for '{playlist_name}': {str(e)}")
            db.session.rollback()
            return None
    
    @staticmethod
    def get_active_version_at_time(playlist_name: str, timestamp: datetime, username: str = None) -> Optional[PlaylistVersion]:
        """
        Get the playlist version that was active at a specific timestamp.
        Uses caching to improve performance for frequently accessed versions.
        
        Args:
            playlist_name: Name of the playlist
            timestamp: The time to query for
            username: Username associated with the playlist
            
        Returns:
            PlaylistVersion object or None if no version found
        """
        try:
            # Create cache key - round timestamp to nearest hour for better cache hits
            rounded_timestamp = timestamp.replace(minute=0, second=0, microsecond=0)
            cache_key = f"{playlist_name}:{username}:{rounded_timestamp.isoformat()}"
            
            # Check cache first
            cached_version = PlaylistVersioningService._get_cached_version(cache_key)
            if cached_version:
                # Verify the cached version is still valid for the exact timestamp
                if (cached_version.active_from <= timestamp and 
                    (cached_version.active_until is None or cached_version.active_until > timestamp)):
                    return cached_version
                else:
                    # Cached version is not valid for this exact timestamp, remove from cache
                    if cache_key in _version_cache:
                        del _version_cache[cache_key]
            
            # Query database
            version = db.session.query(PlaylistVersion).filter(
                and_(
                    PlaylistVersion.playlist_name == playlist_name,
                    PlaylistVersion.username == username if username else True,
                    PlaylistVersion.active_from <= timestamp,
                    or_(
                        PlaylistVersion.active_until.is_(None),
                        PlaylistVersion.active_until > timestamp
                    )
                )
            ).order_by(desc(PlaylistVersion.active_from)).first()
            
            if version:
                logger.debug(f"Found version {version.version_id} active at {timestamp} for '{playlist_name}'")
                # Cache the result
                PlaylistVersioningService._cache_version(cache_key, version)
            else:
                logger.debug(f"No version found active at {timestamp} for '{playlist_name}'")
            
            return version
            
        except SQLAlchemyError as e:
            logger.error(f"Database error querying version for '{playlist_name}' at {timestamp}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error querying version for '{playlist_name}' at {timestamp}: {str(e)}")
            return None
    
    @staticmethod
    def get_version_tracks(version_id: str) -> List[PlaylistVersionTrack]:
        """
        Get all tracks for a specific playlist version.
        
        Args:
            version_id: The version identifier
            
        Returns:
            List of PlaylistVersionTrack objects
        """
        try:
            tracks = db.session.query(PlaylistVersionTrack).filter(
                PlaylistVersionTrack.version_id == version_id
            ).order_by(PlaylistVersionTrack.track_position).all()
            
            logger.debug(f"Retrieved {len(tracks)} tracks for version {version_id}")
            return tracks
            
        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving tracks for version {version_id}: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error retrieving tracks for version {version_id}: {str(e)}")
            return []
    
    @staticmethod
    def find_track_in_version(version_id: str, artist: str, song: str) -> Optional[PlaylistVersionTrack]:
        """
        Find a specific track in a playlist version.
        
        Args:
            version_id: The version identifier
            artist: Track artist
            song: Track title
            
        Returns:
            PlaylistVersionTrack object or None if not found
        """
        try:
            track = db.session.query(PlaylistVersionTrack).filter(
                and_(
                    PlaylistVersionTrack.version_id == version_id,
                    PlaylistVersionTrack.artist == artist,
                    PlaylistVersionTrack.song == song
                )
            ).first()

            if track:
                logger.debug(f"Found track '{artist} - {song}' at position {track.track_position} in version {version_id}")
                return track

            # Fall back to normalized comparison so punctuation/case variants still match
            try:
                from services.spotify_service import normalize_text_for_matching
            except ImportError:
                normalize_text_for_matching = lambda value: str(value or '').lower().strip()

            normalized_artist = normalize_text_for_matching(artist)
            normalized_song = normalize_text_for_matching(song)

            candidate_tracks = db.session.query(PlaylistVersionTrack).filter(
                PlaylistVersionTrack.version_id == version_id
            ).all()

            for candidate in candidate_tracks:
                if (normalize_text_for_matching(candidate.artist) == normalized_artist and
                        normalize_text_for_matching(candidate.song) == normalized_song):
                    logger.debug(
                        "Normalized match for '%s - %s' at position %s in version %s",
                        artist,
                        song,
                        candidate.track_position,
                        version_id
                    )
                    return candidate

            return None

        except SQLAlchemyError as e:
            logger.error(f"Database error finding track '{artist} - {song}' in version {version_id}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error finding track '{artist} - {song}' in version {version_id}: {str(e)}")
            return None
    
    @staticmethod
    def get_all_versioned_playlists() -> List[str]:
        """
        Get list of all playlists that have versions stored.
        
        Returns:
            List of playlist names that have version history
        """
        try:
            playlist_names = db.session.query(PlaylistVersion.playlist_name).distinct().all()
            names = [name[0] for name in playlist_names]
            
            logger.debug(f"Found {len(names)} playlists with versions: {names}")
            return names
            
        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving versioned playlists: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error retrieving versioned playlists: {str(e)}")
            return []
    
    @staticmethod
    def get_version_statistics(playlist_name: str = None) -> Dict[str, Any]:
        """
        Get statistics about stored versions for monitoring.
        
        Args:
            playlist_name: Specific playlist to get stats for, or None for all playlists
            
        Returns:
            Dictionary with version count, storage usage, date range per playlist
        """
        try:
            stats = {}
            
            if playlist_name:
                # Stats for specific playlist
                versions = db.session.query(PlaylistVersion).filter(
                    PlaylistVersion.playlist_name == playlist_name
                ).all()
                
                if versions:
                    track_count = db.session.query(func.sum(PlaylistVersionTrack.id)).join(
                        PlaylistVersion, PlaylistVersionTrack.version_id == PlaylistVersion.version_id
                    ).filter(PlaylistVersion.playlist_name == playlist_name).scalar() or 0
                    
                    stats[playlist_name] = {
                        'version_count': len(versions),
                        'total_tracks': track_count,
                        'oldest_version': min(v.created_at for v in versions),
                        'newest_version': max(v.created_at for v in versions),
                        'active_version': next((v.version_id for v in versions if v.active_until is None), None)
                    }
            else:
                # Stats for all playlists
                all_playlists = PlaylistVersioningService.get_all_versioned_playlists()
                
                for pname in all_playlists:
                    playlist_stats = PlaylistVersioningService.get_version_statistics(pname)
                    stats.update(playlist_stats)
            
            logger.debug(f"Generated version statistics for {len(stats)} playlists")
            return stats
            
        except SQLAlchemyError as e:
            logger.error(f"Database error generating version statistics: {str(e)}")
            return {}
        except Exception as e:
            logger.error(f"Unexpected error generating version statistics: {str(e)}")
            return {}
    
    @staticmethod
    def cleanup_old_versions(playlist_name: str = None, retention_days: int = 7, max_versions: int = 10) -> int:
        """
        Clean up old playlist versions based on retention policy.
        
        Args:
            playlist_name: Name of specific playlist to clean up, or None to clean up all playlists
            retention_days: Keep versions newer than this many days
            max_versions: Keep at least this many recent versions
            
        Returns:
            Number of versions cleaned up across all specified playlists
        """
        try:
            total_cleaned = 0
            
            if playlist_name:
                # Clean up specific playlist
                cleaned = PlaylistVersioningService._cleanup_playlist_versions(
                    playlist_name, retention_days, max_versions
                )
                total_cleaned += cleaned
            else:
                # Clean up all playlists
                all_playlists = PlaylistVersioningService.get_all_versioned_playlists()
                for pname in all_playlists:
                    cleaned = PlaylistVersioningService._cleanup_playlist_versions(
                        pname, retention_days, max_versions
                    )
                    total_cleaned += cleaned
            
            logger.info(f"Cleanup completed: removed {total_cleaned} old versions")
            return total_cleaned
            
        except Exception as e:
            logger.error(f"Error during version cleanup: {str(e)}")
            return 0
    
    @staticmethod
    def cleanup_all_playlists(retention_days: int = 7, max_versions: int = 10) -> Dict[str, int]:
        """
        Clean up old versions for all playlists using global retention policy.
        
        Args:
            retention_days: Keep versions newer than this many days
            max_versions: Keep at least this many recent versions
            
        Returns:
            Dictionary mapping playlist names to number of versions cleaned up
        """
        try:
            cleanup_results = {}
            all_playlists = PlaylistVersioningService.get_all_versioned_playlists()
            
            for playlist_name in all_playlists:
                cleaned = PlaylistVersioningService._cleanup_playlist_versions(
                    playlist_name, retention_days, max_versions
                )
                cleanup_results[playlist_name] = cleaned
            
            total_cleaned = sum(cleanup_results.values())
            logger.info(f"Global cleanup completed: removed {total_cleaned} versions across {len(cleanup_results)} playlists")
            
            return cleanup_results
            
        except Exception as e:
            logger.error(f"Error during global cleanup: {str(e)}")
            return {}
    
    @staticmethod
    def _cleanup_playlist_versions(playlist_name: str, retention_days: int, max_versions: int) -> int:
        """
        Internal method to clean up versions for a specific playlist.
        
        Args:
            playlist_name: Name of the playlist to clean up
            retention_days: Keep versions newer than this many days
            max_versions: Keep at least this many recent versions
            
        Returns:
            Number of versions cleaned up
        """
        try:
            from datetime import timedelta
            
            cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
            
            # Get all versions for this playlist, ordered by creation date (newest first)
            all_versions = db.session.query(PlaylistVersion).filter(
                PlaylistVersion.playlist_name == playlist_name
            ).order_by(desc(PlaylistVersion.created_at)).all()
            
            if len(all_versions) <= max_versions:
                # Don't clean up if we have fewer than max_versions
                logger.debug(f"Playlist '{playlist_name}' has {len(all_versions)} versions, keeping all (max: {max_versions})")
                return 0
            
            # Determine which versions to keep
            versions_to_keep = []
            versions_to_delete = []
            
            for i, version in enumerate(all_versions):
                # Always keep the most recent max_versions
                if i < max_versions:
                    versions_to_keep.append(version)
                # Keep versions newer than cutoff_date
                elif version.created_at > cutoff_date:
                    versions_to_keep.append(version)
                # Keep the currently active version
                elif version.active_until is None:
                    versions_to_keep.append(version)
                else:
                    versions_to_delete.append(version)
            
            # Check if any versions are still referenced by recent listening history
            if versions_to_delete:
                versions_to_delete = PlaylistVersioningService._filter_referenced_versions(
                    versions_to_delete, retention_days
                )
            
            # Delete the versions and their tracks
            cleaned_count = 0
            for version in versions_to_delete:
                try:
                    # Delete version tracks first (due to foreign key constraint)
                    db.session.query(PlaylistVersionTrack).filter(
                        PlaylistVersionTrack.version_id == version.version_id
                    ).delete()
                    
                    # Delete the version record
                    db.session.delete(version)
                    cleaned_count += 1
                    
                    logger.debug(f"Deleted version {version.version_id} for playlist '{playlist_name}'")
                    
                except SQLAlchemyError as e:
                    logger.error(f"Error deleting version {version.version_id}: {str(e)}")
                    db.session.rollback()
                    continue
            
            if cleaned_count > 0:
                db.session.commit()
                logger.info(f"Cleaned up {cleaned_count} old versions for playlist '{playlist_name}'")
            
            return cleaned_count
            
        except Exception as e:
            logger.error(f"Error cleaning up versions for playlist '{playlist_name}': {str(e)}")
            db.session.rollback()
            return 0
    
    @staticmethod
    def _filter_referenced_versions(versions_to_delete: List[PlaylistVersion], retention_days: int) -> List[PlaylistVersion]:
        """
        Filter out versions that are still referenced by recent listening history.
        
        Args:
            versions_to_delete: List of versions candidate for deletion
            retention_days: Number of days to check for references
            
        Returns:
            Filtered list of versions safe to delete
        """
        try:
            from datetime import timedelta
            from models import PlayedTrack
            
            # Check for recent played tracks that might reference these versions
            cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
            
            # Get recent played tracks for the same playlist
            if not versions_to_delete:
                return []
            
            playlist_name = versions_to_delete[0].playlist_name
            recent_tracks = db.session.query(PlayedTrack).filter(
                and_(
                    PlayedTrack.playlist_name == playlist_name,
                    PlayedTrack.played_at > cutoff_date
                )
            ).all()
            
            if not recent_tracks:
                # No recent tracks, safe to delete all versions
                return versions_to_delete
            
            # For now, be conservative and keep versions that might be referenced
            # In a more sophisticated implementation, we could correlate specific tracks
            safe_to_delete = []
            for version in versions_to_delete:
                # Only delete versions older than the oldest recent track
                oldest_recent_track = min(track.played_at for track in recent_tracks)
                if version.active_until and version.active_until < oldest_recent_track:
                    safe_to_delete.append(version)
            
            logger.debug(f"Filtered {len(versions_to_delete)} candidates to {len(safe_to_delete)} safe to delete")
            return safe_to_delete
            
        except Exception as e:
            logger.error(f"Error filtering referenced versions: {str(e)}")
            # Be conservative - don't delete anything if we can't determine references
            return []
    
    @staticmethod
    def _get_cached_version(cache_key: str) -> Optional[PlaylistVersion]:
        """Get a version from cache if it exists and is not expired."""
        if cache_key in _version_cache:
            cached_data, timestamp = _version_cache[cache_key]
            if datetime.utcnow() - timestamp < timedelta(seconds=_cache_ttl):
                logger.debug(f"Cache hit for version key: {cache_key}")
                return cached_data
            else:
                # Remove expired entry
                del _version_cache[cache_key]
                logger.debug(f"Cache expired for version key: {cache_key}")
        return None
    
    @staticmethod
    def _cache_version(cache_key: str, version: PlaylistVersion):
        """Cache a version with timestamp."""
        _version_cache[cache_key] = (version, datetime.utcnow())
        logger.debug(f"Cached version: {cache_key}")
        
        # Simple cache size management - keep only last 100 entries
        if len(_version_cache) > 100:
            # Remove oldest entries
            sorted_cache = sorted(_version_cache.items(), key=lambda x: x[1][1])
            for key, _ in sorted_cache[:20]:  # Remove oldest 20 entries
                del _version_cache[key]
    
    @staticmethod
    def clear_version_cache():
        """Clear the version cache."""
        global _version_cache
        _version_cache.clear()
        logger.info("Version cache cleared")
    
    @staticmethod
    def health_check() -> Dict[str, Any]:
        """
        Perform a health check of the versioning system.
        
        Returns:
            Dictionary with health status and system metrics
        """
        try:
            health_status = {
                'status': 'healthy',
                'timestamp': datetime.utcnow().isoformat(),
                'cache_size': len(_version_cache),
                'database_accessible': False,
                'versioned_playlists': 0,
                'total_versions': 0,
                'errors': []
            }
            
            # Test database connectivity
            try:
                total_versions = db.session.query(func.count(PlaylistVersion.id)).scalar()
                versioned_playlists = len(PlaylistVersioningService.get_all_versioned_playlists())
                
                health_status['database_accessible'] = True
                health_status['total_versions'] = total_versions
                health_status['versioned_playlists'] = versioned_playlists
                
            except Exception as db_error:
                health_status['status'] = 'degraded'
                health_status['errors'].append(f"Database error: {str(db_error)}")
            
            # Check configuration
            try:
                from services.playlist_versioning_config import get_versioning_config
                config = get_versioning_config()
                health_status['versioning_enabled'] = config.is_enabled()
                health_status['retention_days'] = config.get_retention_days()
                health_status['max_versions'] = config.get_max_versions()
            except Exception as config_error:
                health_status['status'] = 'degraded'
                health_status['errors'].append(f"Configuration error: {str(config_error)}")
            
            # Overall status determination
            if health_status['errors']:
                if health_status['status'] == 'healthy':
                    health_status['status'] = 'degraded'
            
            logger.info(f"Health check completed: {health_status['status']}")
            return health_status
            
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return {
                'status': 'unhealthy',
                'timestamp': datetime.utcnow().isoformat(),
                'error': str(e)
            }
