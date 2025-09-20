from flask import render_template, jsonify, request, send_file, abort
from flask_login import login_required, current_user
from . import admin_bp
from services.duplicate_detection_service import DuplicateDetectionService
from services.duplicate_persistence_service import DuplicatePersistenceService
from services.itunes_comparison_service import ITunesComparisonService
from services.error_handling_service import get_error_service
from services.audit_logging_service import get_audit_service
from models import Track, DuplicateAnalysisResult
from extensions import db
import logging
import os
import traceback
from datetime import datetime

@admin_bp.route('/duplicates')
@login_required
def duplicate_management():
    """Main duplicate management interface."""
    return render_template('admin/duplicate_management.html')

@admin_bp.route('/duplicates/itunes-status')
@login_required
def itunes_status():
    """Get iTunes integration status with comprehensive error reporting."""
    error_service = get_error_service()
    audit_service = get_audit_service()
    
    try:
        itunes_service = ITunesComparisonService()
        
        # Check if iTunes is available
        is_available = itunes_service.is_available()
        
        if is_available:
            # Get statistics for available library
            stats = itunes_service.get_itunes_statistics()
            
            # Log successful iTunes validation
            audit_service.log_itunes_validation({
                'valid': True,
                'total_tracks': stats.get('total_tracks', 0),
                'xml_path': stats.get('xml_path')
            })
            
            return jsonify({
                'success': True,
                'available': True,
                'total_tracks': stats.get('total_tracks', 0),
                'xml_path': stats.get('xml_path'),
                'tracks_with_play_count': stats.get('tracks_with_play_count', 0),
                'unique_genres': stats.get('unique_genres', 0)
            })
        else:
            # Get initialization error details
            error_details = itunes_service.get_initialization_error()
            
            if error_details:
                # Log iTunes validation failure
                audit_service.log_itunes_validation({
                    'valid': False,
                    'errors': [error_details.get('error_message', 'Unknown error')],
                    'xml_path': error_details.get('context', {}).get('xml_path')
                })
                
                return jsonify({
                    'success': False,
                    'available': False,
                    'total_tracks': 0,
                    'error_details': error_details,
                    'title': error_details.get('title', 'iTunes Access Error'),
                    'message': error_details.get('error_message', 'iTunes library not available'),
                    'suggestions': error_details.get('suggestions', [])
                })
            else:
                # Generic unavailable response
                return jsonify({
                    'success': False,
                    'available': False,
                    'total_tracks': 0,
                    'error': 'iTunes library not configured or available'
                })
        
    except Exception as e:
        # Handle unexpected errors
        error_response = error_service.handle_error(
            e,
            context={'operation': 'itunes_status_check'}
        )
        
        # Log the error
        audit_service.log_itunes_validation({
            'valid': False,
            'errors': [str(e)],
            'xml_path': None
        })
        
        return jsonify(error_response), 500

@admin_bp.route('/duplicates/analyze')
@login_required
def analyze_duplicates():
    """Analyze duplicates and return results with iTunes integration."""
    try:
        # Get parameters
        search_term = request.args.get('search', '').strip()
        sort_by = request.args.get('sort_by', 'artist')
        min_confidence = float(request.args.get('min_confidence', 0.0))
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
        
        # Initialize services
        duplicate_service = DuplicateDetectionService()
        itunes_service = ITunesComparisonService()
        
        # Find duplicates with filtering
        duplicate_groups = duplicate_service.find_duplicates(
            search_term=search_term if search_term else None,
            sort_by=sort_by,
            min_confidence=min_confidence
        )
        
        # Get overall analysis
        analysis = duplicate_service.get_overall_analysis(duplicate_groups)
        
        # Apply pagination
        total_groups = len(duplicate_groups)
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        paginated_groups = duplicate_groups[start_index:end_index]
        
        # Add iTunes matches for each group
        enhanced_groups = []
        for group in paginated_groups:
            # Convert to dict for JSON serialization
            group_dict = {
                'canonical_song': {
                    'id': group.canonical_song.id,
                    'song': group.canonical_song.song,
                    'artist': group.canonical_song.artist,
                    'album': group.canonical_song.album,
                    'play_cnt': group.canonical_song.play_cnt,
                    'last_play_dt': group.canonical_song.last_play_dt.isoformat() if group.canonical_song.last_play_dt else None,
                    'date_added': group.canonical_song.date_added.isoformat() if group.canonical_song.date_added else None
                },
                'duplicates': [],
                'similarity_scores': group.similarity_scores,
                'suggested_action': group.suggested_action
            }
            
            # Add duplicates
            for duplicate in group.duplicates:
                group_dict['duplicates'].append({
                    'id': duplicate.id,
                    'song': duplicate.song,
                    'artist': duplicate.artist,
                    'album': duplicate.album,
                    'play_cnt': duplicate.play_cnt,
                    'last_play_dt': duplicate.last_play_dt.isoformat() if duplicate.last_play_dt else None,
                    'date_added': duplicate.date_added.isoformat() if duplicate.date_added else None
                })
            
            # Add iTunes matches if available
            if itunes_service.is_available():
                itunes_matches = itunes_service.find_itunes_matches(group)
                group_dict['itunes_matches'] = {}
                
                for track_id, match in itunes_matches.items():
                    group_dict['itunes_matches'][track_id] = {
                        'found': match.found,
                        'match_type': match.match_type,
                        'confidence_score': match.confidence_score,
                        'metadata_differences': match.metadata_differences,
                        'itunes_track': {
                            'name': match.itunes_track.name,
                            'artist': match.itunes_track.artist,
                            'album': match.itunes_track.album,
                            'play_count': match.itunes_track.play_count,
                            'genre': match.itunes_track.genre
                        } if match.itunes_track else None
                    }
            
            enhanced_groups.append(group_dict)
        
        return jsonify({
            'success': True,
            'duplicate_groups': enhanced_groups,
            'analysis': {
                'total_groups': analysis.total_groups,
                'total_duplicates': analysis.total_duplicates,
                'potential_deletions': analysis.potential_deletions,
                'estimated_space_savings': analysis.estimated_space_savings,
                'groups_with_high_confidence': analysis.groups_with_high_confidence,
                'average_similarity_score': analysis.average_similarity_score
            },
            'pagination': {
                'current_page': page,
                'per_page': per_page,
                'total_groups': total_groups,
                'total_pages': (total_groups + per_page - 1) // per_page,
                'has_prev': page > 1,
                'has_next': end_index < total_groups
            },
            'itunes_available': itunes_service.is_available()
        })
        
    except Exception as e:
        logging.error(f"Error analyzing duplicates: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/duplicates/analyze-with-persistence', methods=['POST'])
@login_required
def analyze_duplicates_with_persistence():
    """Start duplicate analysis with automatic persistence and progress tracking."""
    try:
        # Get parameters from query string
        search_term = request.args.get('search', '').strip()
        sort_by = request.args.get('sort_by', 'artist')
        min_confidence = float(request.args.get('min_confidence', 0.0))
        force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
        
        # Initialize services
        duplicate_service = DuplicateDetectionService()
        persistence_service = DuplicatePersistenceService()
        
        # Check if we should use existing analysis
        if not force_refresh:
            latest_analysis = persistence_service.get_latest_analysis(
                user_id=current_user.id,
                search_term=search_term if search_term else None
            )
            
            if latest_analysis and not persistence_service.is_analysis_stale(latest_analysis):
                # Return existing analysis
                return jsonify({
                    'success': True,
                    'analysis_id': latest_analysis.analysis_id,
                    'using_existing': True,
                    'message': 'Using existing fresh analysis'
                })
        
        # Start new analysis with persistence
        analysis_result = duplicate_service.find_duplicates_with_persistence(
            search_term=search_term if search_term else None,
            sort_by=sort_by,
            min_confidence=min_confidence,
            user_id=current_user.id,
            force_refresh=force_refresh
        )
        
        if analysis_result['success']:
            return jsonify({
                'success': True,
                'analysis_id': analysis_result['analysis_id'],
                'using_existing': False,
                'message': 'Analysis started successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': analysis_result.get('error', 'Failed to start analysis')
            }), 500
            
    except Exception as e:
        logging.error(f"Error starting analysis with persistence: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/duplicates/filter')
@login_required
def filter_duplicates():
    """Real-time filtering of duplicate groups for search and sorting with performance optimizations."""
    import time
    start_time = time.time()
    
    try:
        # Get parameters
        search_term = request.args.get('search', '').strip()
        sort_by = request.args.get('sort_by', 'artist')
        min_confidence = float(request.args.get('min_confidence', 0.0))
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
        optimize = request.args.get('optimize', 'false').lower() == 'true'
        
        # Performance optimization: limit per_page for large datasets
        if per_page > 50:
            per_page = 50
        
        query_start = time.time()
        
        # Initialize services
        duplicate_service = DuplicateDetectionService()
        itunes_service = ITunesComparisonService()
        
        # Find and filter duplicates with performance optimizations
        if optimize:
            # Use optimized query for better performance with timeout
            result = duplicate_service.find_duplicates_with_timeout(
                search_term=search_term if search_term else None,
                sort_by=sort_by,
                min_confidence=min_confidence,
                timeout_seconds=15  # 15 second timeout for filter requests
            )
            
            if not result['success']:
                return jsonify({
                    'success': False,
                    'error': result['error'],
                    'timed_out': result['timed_out']
                }), 408  # Request Timeout
            
            duplicate_groups = result['duplicate_groups']
        else:
            # Use cached results when possible
            duplicate_groups = duplicate_service.find_duplicates(
                search_term=search_term if search_term else None,
                sort_by=sort_by,
                min_confidence=min_confidence,
                use_cache=True
            )
        
        query_time = (time.time() - query_start) * 1000  # Convert to milliseconds
        processing_start = time.time()
        
        # Apply pagination
        total_groups = len(duplicate_groups)
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        paginated_groups = duplicate_groups[start_index:end_index]
        
        # Convert to lightweight format for faster response
        filtered_groups = []
        for group in paginated_groups:
            # Calculate average confidence once
            avg_confidence = sum(group.similarity_scores.values()) / len(group.similarity_scores) if group.similarity_scores else 0
            
            group_dict = {
                'canonical_song': {
                    'id': group.canonical_song.id,
                    'song': group.canonical_song.song,
                    'artist': group.canonical_song.artist,
                    'album': group.canonical_song.album,
                    'play_cnt': group.canonical_song.play_cnt,
                    'last_play_dt': group.canonical_song.last_play_dt.isoformat() if group.canonical_song.last_play_dt else None,
                    'date_added': group.canonical_song.date_added.isoformat() if group.canonical_song.date_added else None
                },
                'duplicates': [{
                    'id': duplicate.id,
                    'song': duplicate.song,
                    'artist': duplicate.artist,
                    'album': duplicate.album,
                    'play_cnt': duplicate.play_cnt,
                    'last_play_dt': duplicate.last_play_dt.isoformat() if duplicate.last_play_dt else None,
                    'date_added': duplicate.date_added.isoformat() if duplicate.date_added else None
                } for duplicate in group.duplicates],
                'similarity_scores': group.similarity_scores,
                'suggested_action': group.suggested_action,
                'average_confidence': avg_confidence,
                'duplicate_count': len(group.duplicates)
            }
            
            # Add iTunes matches only if requested and available
            if not optimize and itunes_service.is_available():
                try:
                    itunes_matches = itunes_service.find_itunes_matches(group)
                    if itunes_matches:
                        group_dict['itunes_matches'] = {}
                        for track_id, match in itunes_matches.items():
                            group_dict['itunes_matches'][track_id] = {
                                'found': match.found,
                                'match_type': match.match_type,
                                'confidence_score': match.confidence_score
                            }
                except Exception as e:
                    logging.warning(f"Error getting iTunes matches for group: {e}")
            
            filtered_groups.append(group_dict)
        
        processing_time = (time.time() - processing_start) * 1000
        total_time = (time.time() - start_time) * 1000
        
        response_data = {
            'success': True,
            'duplicate_groups': filtered_groups,
            'pagination': {
                'current_page': page,
                'per_page': per_page,
                'total_groups': total_groups,
                'total_pages': (total_groups + per_page - 1) // per_page,
                'has_prev': page > 1,
                'has_next': end_index < total_groups
            },
            'filters': {
                'search_term': search_term,
                'sort_by': sort_by,
                'min_confidence': min_confidence
            }
        }
        
        # Add performance metrics if optimization is enabled
        if optimize:
            response_data['performance_metrics'] = {
                'query_time': round(query_time, 2),
                'processing_time': round(processing_time, 2),
                'total_time': round(total_time, 2),
                'total_results': total_groups,
                'filtered_results': len(filtered_groups)
            }
        
        return jsonify(response_data)
        
    except Exception as e:
        logging.error(f"Error filtering duplicates: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/duplicates/delete', methods=['POST'])
@login_required
def delete_duplicate():
    """Delete individual duplicate song with comprehensive error handling and audit logging."""
    error_service = get_error_service()
    audit_service = get_audit_service()
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        track_id = data.get('track_id')
        if not track_id:
            return jsonify({
                'success': False,
                'error': 'Track ID is required'
            }), 400
        
        # Validate track_id is a positive integer
        try:
            track_id = int(track_id)
            if track_id <= 0:
                raise ValueError("Track ID must be positive")
        except (ValueError, TypeError):
            error_response = error_service.handle_error(
                ValueError("Invalid track ID format"),
                context={'track_id': track_id, 'operation': 'delete_duplicate'}
            )
            return jsonify(error_response), 400
        
        # Validate track exists
        track = Track.query.get(track_id)
        if not track:
            return jsonify({
                'success': False,
                'error': f'Track with ID {track_id} not found'
            }), 404
        
        # Store track info for response and logging
        track_info = {
            'id': track.id,
            'song': track.song or 'Unknown',
            'artist': track.artist or 'Unknown',
            'album': track.album or 'Unknown',
            'play_cnt': track.play_cnt or 0
        }
        
        # Validate deletion with warnings
        is_valid, warnings = error_service.validate_track_deletion([track_id])
        if not is_valid:
            return jsonify({
                'success': False,
                'error': 'Track deletion validation failed',
                'warnings': warnings
            }), 400
        
        # Begin transaction with error handling
        try:
            # Delete the track
            db.session.delete(track)
            db.session.commit()
            
            # Update resolution status in saved analyses and log cleanup action
            try:
                from services.duplicate_persistence_service import DuplicatePersistenceService
                import time
                
                start_time = time.time()
                persistence_service = DuplicatePersistenceService()
                
                resolution_update = persistence_service.update_resolution_status_on_track_deletion(
                    [track_id], 
                    user_id=current_user.id
                )
                
                processing_time = time.time() - start_time
                
                # Log the cleanup action
                action_id = persistence_service.log_cleanup_action(
                    action_type='track_deleted',
                    operation_type='single_delete',
                    user_id=current_user.id,
                    affected_track_ids=[track_id],
                    affected_group_ids=resolution_update.get('updated_groups', []),
                    resolution_action=resolution_update.get('resolution_summary', {}).get('fully_resolved', 0) > 0 and 'duplicates_deleted' or None,
                    cleanup_strategy='manual_selection',
                    processing_time_seconds=processing_time,
                    context_data={'track_info': track_info},
                    success=True
                )
                
                logging.info(f"Updated resolution status for track deletion: {resolution_update}, action_id: {action_id}")
            except Exception as resolution_error:
                # Don't fail the deletion if resolution tracking fails
                logging.warning(f"Failed to update resolution status: {str(resolution_error)}")
            
            # Log successful deletion
            audit_service.log_duplicate_deletion(track_info, success=True)
            
            logging.info(f"Deleted duplicate track: {track_info['song']} by {track_info['artist']} (ID: {track_id}, play_cnt: {track_info['play_cnt']})")
            
            response = {
                'success': True,
                'message': f'Successfully deleted "{track_info["song"]}" by {track_info["artist"]}',
                'deleted_track': track_info
            }
            
            if warnings:
                response['warnings'] = warnings
            
            return jsonify(response)
            
        except Exception as db_error:
            # Handle database transaction error with automatic rollback
            error_response = error_service.handle_database_transaction_error(
                db_error,
                operation_context={
                    'operation': 'delete_duplicate',
                    'track_id': track_id,
                    'track_info': track_info
                }
            )
            
            # Log failed deletion
            audit_service.log_duplicate_deletion(
                track_info, 
                success=False, 
                error_message=str(db_error)
            )
            
            return jsonify(error_response), 500
        
    except Exception as e:
        # Handle any other unexpected errors
        error_response = error_service.handle_error(
            e,
            context={
                'operation': 'delete_duplicate',
                'track_id': track_id if 'track_id' in locals() else None,
                'request_data': data if 'data' in locals() else None
            }
        )
        
        # Ensure transaction is rolled back
        try:
            db.session.rollback()
        except:
            pass
        
        return jsonify(error_response), 500

@admin_bp.route('/duplicates/bulk-delete', methods=['POST'])
@login_required
def bulk_delete_duplicates():
    """Delete multiple duplicate songs with comprehensive error handling and audit logging."""
    error_service = get_error_service()
    audit_service = get_audit_service()
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        track_ids = data.get('track_ids', [])
        if not track_ids or not isinstance(track_ids, list):
            return jsonify({
                'success': False,
                'error': 'Track IDs list is required'
            }), 400
        
        # Validate all track IDs are positive integers
        validated_ids = []
        for track_id in track_ids:
            try:
                validated_id = int(track_id)
                if validated_id <= 0:
                    raise ValueError("Track ID must be positive")
                validated_ids.append(validated_id)
            except (ValueError, TypeError):
                error_response = error_service.handle_error(
                    ValueError(f"Invalid track ID format: {track_id}"),
                    context={'operation': 'bulk_delete', 'invalid_id': track_id}
                )
                return jsonify(error_response), 400
        
        # Validate deletion with comprehensive checks
        is_valid, warnings = error_service.validate_track_deletion(validated_ids)
        if not is_valid:
            return jsonify({
                'success': False,
                'error': 'Bulk deletion validation failed',
                'warnings': warnings
            }), 400
        
        # Validate all tracks exist
        tracks = Track.query.filter(Track.id.in_(validated_ids)).all()
        found_ids = {track.id for track in tracks}
        missing_ids = set(validated_ids) - found_ids
        
        if missing_ids:
            return jsonify({
                'success': False,
                'error': f'Tracks not found: {list(missing_ids)}'
            }), 404
        
        # Store track info for response and logging
        deleted_tracks = []
        total_play_count = 0
        for track in tracks:
            play_cnt = track.play_cnt or 0
            total_play_count += play_cnt
            deleted_tracks.append({
                'id': track.id,
                'song': track.song or 'Unknown',
                'artist': track.artist or 'Unknown',
                'album': track.album or 'Unknown',
                'play_cnt': play_cnt
            })
        
        # Begin transaction with comprehensive error handling
        try:
            # Delete all tracks in a single transaction
            Track.query.filter(Track.id.in_(validated_ids)).delete(synchronize_session=False)
            db.session.commit()
            
            # Update resolution status in saved analyses and log cleanup action
            try:
                from services.duplicate_persistence_service import DuplicatePersistenceService
                import time
                
                start_time = time.time()
                persistence_service = DuplicatePersistenceService()
                
                resolution_update = persistence_service.update_resolution_status_on_track_deletion(
                    validated_ids, 
                    user_id=current_user.id
                )
                
                processing_time = time.time() - start_time
                
                # Log the cleanup action
                action_id = persistence_service.log_cleanup_action(
                    action_type='bulk_cleanup',
                    operation_type='bulk_delete',
                    user_id=current_user.id,
                    affected_track_ids=validated_ids,
                    affected_group_ids=resolution_update.get('updated_groups', []),
                    resolution_action='bulk_deletion',
                    cleanup_strategy='manual_selection',
                    processing_time_seconds=processing_time,
                    context_data={
                        'deleted_tracks': deleted_tracks,
                        'total_play_count': total_play_count
                    },
                    success=True
                )
                
                logging.info(f"Updated resolution status for bulk deletion: {resolution_update}, action_id: {action_id}")
            except Exception as resolution_error:
                # Don't fail the deletion if resolution tracking fails
                logging.warning(f"Failed to update resolution status: {str(resolution_error)}")
            
            # Log successful bulk deletion
            audit_service.log_bulk_deletion(
                deleted_tracks, 
                deletion_strategy='manual_selection',
                success=True
            )
            
            logging.info(f"Bulk deleted {len(deleted_tracks)} duplicate tracks (total play count: {total_play_count})")
            
            response = {
                'success': True,
                'message': f'Successfully deleted {len(deleted_tracks)} duplicate songs',
                'deleted_count': len(deleted_tracks),
                'deleted_tracks': deleted_tracks,
                'total_play_count': total_play_count
            }
            
            if warnings:
                response['warnings'] = warnings
            
            return jsonify(response)
            
        except Exception as db_error:
            # Handle database transaction error with automatic rollback
            error_response = error_service.handle_database_transaction_error(
                db_error,
                operation_context={
                    'operation': 'bulk_delete',
                    'track_count': len(validated_ids),
                    'track_ids': validated_ids,
                    'total_play_count': total_play_count
                }
            )
            
            # Log failed bulk deletion
            audit_service.log_bulk_deletion(
                deleted_tracks,
                deletion_strategy='manual_selection',
                success=False,
                error_message=str(db_error)
            )
            
            return jsonify(error_response), 500
        
    except Exception as e:
        # Handle any other unexpected errors
        error_response = error_service.handle_error(
            e,
            context={
                'operation': 'bulk_delete',
                'track_ids': validated_ids if 'validated_ids' in locals() else None,
                'request_data': data if 'data' in locals() else None
            }
        )
        
        # Ensure transaction is rolled back
        try:
            db.session.rollback()
        except:
            pass
        
        return jsonify(error_response), 500

@admin_bp.route('/duplicates/smart-delete', methods=['POST'])
@login_required
def smart_delete_duplicates():
    """Smart bulk deletion with options like keep iTunes version, keep most played, etc."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        duplicate_groups = data.get('duplicate_groups', [])
        deletion_strategy = data.get('strategy', 'keep_most_played')  # Options: keep_most_played, keep_itunes_version, keep_shortest_title
        
        if not duplicate_groups or not isinstance(duplicate_groups, list):
            return jsonify({
                'success': False,
                'error': 'Duplicate groups list is required'
            }), 400
        
        # Validate strategy
        valid_strategies = ['keep_most_played', 'keep_itunes_version', 'keep_shortest_title', 'keep_canonical']
        if deletion_strategy not in valid_strategies:
            return jsonify({
                'success': False,
                'error': f'Invalid strategy. Must be one of: {valid_strategies}'
            }), 400
        
        # Initialize services for smart deletion
        duplicate_service = DuplicateDetectionService()
        itunes_service = ITunesComparisonService()
        
        tracks_to_delete = []
        deletion_summary = {
            'groups_processed': 0,
            'tracks_to_delete': 0,
            'tracks_to_keep': 0,
            'strategy_used': deletion_strategy
        }
        
        # Process each duplicate group
        for group_data in duplicate_groups:
            group_id = group_data.get('group_id')
            track_ids = group_data.get('track_ids', [])
            
            if not track_ids:
                continue
            
            # Get tracks for this group
            tracks = Track.query.filter(Track.id.in_(track_ids)).all()
            if len(tracks) < 2:  # Need at least 2 tracks to have duplicates
                continue
            
            deletion_summary['groups_processed'] += 1
            
            # Apply deletion strategy
            if deletion_strategy == 'keep_most_played':
                # Keep the track with highest play count
                tracks_sorted = sorted(tracks, key=lambda t: t.play_cnt or 0, reverse=True)
                keep_track = tracks_sorted[0]
                delete_tracks = tracks_sorted[1:]
                
            elif deletion_strategy == 'keep_itunes_version':
                # Keep the track that matches iTunes library
                keep_track = None
                delete_tracks = []
                
                if itunes_service.is_available():
                    # Find iTunes matches for all tracks
                    for track in tracks:
                        # Create a simple group for iTunes matching
                        from services.duplicate_detection_service import DuplicateGroup
                        temp_group = DuplicateGroup(
                            canonical_song=track,
                            duplicates=[],
                            similarity_scores={},
                            suggested_action='keep'
                        )
                        itunes_matches = itunes_service.find_itunes_matches(temp_group)
                        if track.id in itunes_matches and itunes_matches[track.id].found and itunes_matches[track.id].match_type == 'exact':
                            keep_track = track
                            break
                
                # If no exact iTunes match found, fall back to most played
                if not keep_track:
                    tracks_sorted = sorted(tracks, key=lambda t: t.play_cnt or 0, reverse=True)
                    keep_track = tracks_sorted[0]
                    delete_tracks = tracks_sorted[1:]
                else:
                    delete_tracks = [t for t in tracks if t.id != keep_track.id]
                    
            elif deletion_strategy == 'keep_shortest_title':
                # Keep the track with the shortest title (likely the original)
                tracks_sorted = sorted(tracks, key=lambda t: len(t.song or ''))
                keep_track = tracks_sorted[0]
                delete_tracks = tracks_sorted[1:]
                
            elif deletion_strategy == 'keep_canonical':
                # Use the duplicate service to suggest canonical version
                canonical_track = duplicate_service.suggest_canonical_version(tracks)
                keep_track = canonical_track
                delete_tracks = [t for t in tracks if t.id != canonical_track.id]
            
            # Add to deletion list
            tracks_to_delete.extend(delete_tracks)
            deletion_summary['tracks_to_delete'] += len(delete_tracks)
            deletion_summary['tracks_to_keep'] += 1
        
        # Validate batch size limit
        max_batch_size = 200  # Higher limit for smart deletion
        if len(tracks_to_delete) > max_batch_size:
            return jsonify({
                'success': False,
                'error': f'Smart deletion would delete {len(tracks_to_delete)} tracks, which exceeds the maximum of {max_batch_size}'
            }), 400
        
        if not tracks_to_delete:
            return jsonify({
                'success': True,
                'message': 'No tracks selected for deletion based on the chosen strategy',
                'deletion_summary': deletion_summary
            })
        
        # Store track info for response
        deleted_tracks = []
        for track in tracks_to_delete:
            deleted_tracks.append({
                'id': track.id,
                'song': track.song or 'Unknown',
                'artist': track.artist or 'Unknown',
                'album': track.album or 'Unknown',
                'play_cnt': track.play_cnt or 0
            })
        
        # Delete all selected tracks in a single transaction
        track_ids_to_delete = [track.id for track in tracks_to_delete]
        Track.query.filter(Track.id.in_(track_ids_to_delete)).delete(synchronize_session=False)
        db.session.commit()
        
        logging.info(f"Smart deleted {len(deleted_tracks)} duplicate tracks using strategy: {deletion_strategy}")
        
        return jsonify({
            'success': True,
            'message': f'Successfully deleted {len(deleted_tracks)} duplicate songs using {deletion_strategy} strategy',
            'deleted_count': len(deleted_tracks),
            'deleted_tracks': deleted_tracks,
            'deletion_summary': deletion_summary
        })
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in smart deletion: {e}")
        return jsonify({
            'success': False,
            'error': f'Database error: {str(e)}'
        }), 500

@admin_bp.route('/duplicates/cache/stats')
@login_required
def cache_stats():
    """Get cache statistics for monitoring."""
    try:
        from services.duplicate_cache_service import get_duplicate_cache
        cache_service = get_duplicate_cache()
        
        # Get cache stats
        cache_stats = cache_service.get_cache_stats()
        
        # Get database performance stats
        duplicate_service = DuplicateDetectionService()
        db_stats = duplicate_service.get_database_performance_stats()
        
        return jsonify({
            'success': True,
            'cache_stats': cache_stats,
            'database_stats': db_stats
        })
        
    except Exception as e:
        logging.error(f"Error getting cache stats: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/duplicates/cache/clear', methods=['POST'])
@login_required
def clear_cache():
    """Clear all cached duplicate detection results."""
    try:
        from services.duplicate_cache_service import get_duplicate_cache
        cache_service = get_duplicate_cache()
        cache_service.invalidate_cache()
        
        # Also clear any service-level caches
        duplicate_service = DuplicateDetectionService()
        duplicate_service.invalidate_caches()
        
        return jsonify({
            'success': True,
            'message': 'Cache cleared successfully'
        })
        
    except Exception as e:
        logging.error(f"Error clearing cache: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/duplicates/performance/optimize', methods=['POST'])
@login_required
def optimize_performance():
    """Run performance optimization tasks."""
    try:
        duplicate_service = DuplicateDetectionService()
        
        # Get current performance stats
        db_stats = duplicate_service.get_database_performance_stats()
        
        optimizations_applied = []
        
        # Clear cache to force fresh results
        duplicate_service.invalidate_caches()
        optimizations_applied.append("Cache cleared")
        
        # Run ANALYZE on the tracks table to update statistics
        try:
            db.session.execute(text("ANALYZE tracks"))
            db.session.commit()
            optimizations_applied.append("Database statistics updated")
        except Exception as e:
            logging.warning(f"Could not run ANALYZE: {e}")
        
        # Get updated stats
        updated_stats = duplicate_service.get_database_performance_stats()
        
        return jsonify({
            'success': True,
            'message': 'Performance optimization completed',
            'optimizations_applied': optimizations_applied,
            'before_stats': db_stats,
            'after_stats': updated_stats
        })
        
    except Exception as e:
        logging.error(f"Error optimizing performance: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# DUPLICATE ANALYSIS PERSISTENCE MANAGEMENT ROUTES
# ============================================================================

@admin_bp.route('/duplicates/analyses')
@login_required
def list_analyses():
    """List saved duplicate analyses for current user with age indicators and quick actions."""
    try:
        # Get pagination parameters
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
        
        # Initialize persistence service
        persistence_service = DuplicatePersistenceService()
        
        # Get user analyses with pagination
        offset = (page - 1) * per_page
        analyses = persistence_service.get_user_analyses(
            user_id=current_user.id,
            limit=per_page,
            offset=offset
        )
        
        # Get total count for pagination
        total_count = persistence_service.get_user_analyses_count(current_user.id)
        
        # Enhance each analysis with age information and summary
        enhanced_analyses = []
        for analysis in analyses:
            # Get age information
            age_info = persistence_service.get_analysis_age_info(analysis)
            
            # Get library change summary
            library_changes = persistence_service.get_library_change_summary(analysis)
            
            # Get analysis summary
            summary = persistence_service.get_analysis_summary(analysis)
            
            enhanced_analysis = {
                'analysis_id': analysis.analysis_id,
                'created_at': analysis.created_at.isoformat(),
                'completed_at': analysis.completed_at.isoformat() if analysis.completed_at else None,
                'status': analysis.status,
                'search_term': analysis.search_term,
                'sort_by': analysis.sort_by,
                'min_confidence': analysis.min_confidence,
                'total_groups': analysis.total_groups_found,
                'total_duplicates': analysis.total_duplicates_found,
                'processing_time': analysis.processing_time_seconds,
                'age_info': age_info,
                'library_changes': library_changes,
                'summary': summary
            }
            
            enhanced_analyses.append(enhanced_analysis)
        
        # Calculate pagination info
        total_pages = (total_count + per_page - 1) // per_page
        
        return jsonify({
            'success': True,
            'analyses': enhanced_analyses,
            'pagination': {
                'current_page': page,
                'per_page': per_page,
                'total_count': total_count,
                'total_pages': total_pages,
                'has_prev': page > 1,
                'has_next': page < total_pages
            }
        })
        
    except Exception as e:
        logging.error(f"Error listing analyses: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/duplicates/analysis/<analysis_id>')
@login_required
def get_analysis(analysis_id):
    """Get specific analysis results with age notification and refresh options."""
    try:
        # Initialize persistence service
        persistence_service = DuplicatePersistenceService()
        
        # Load the analysis result
        logging.info(f"GET /admin/duplicates/analysis/{analysis_id} - Loading analysis result")
        analysis_result = persistence_service.load_analysis_result(analysis_id)
        
        if not analysis_result:
            logging.error(f"Analysis {analysis_id} not found in database")
            return jsonify({
                'success': False,
                'error': 'Analysis not found'
            }), 404
        
        logging.info(f"Analysis {analysis_id} loaded successfully, status: {analysis_result.status}, groups: {analysis_result.total_groups_found}")
        
        # Security check - ensure user owns this analysis
        if analysis_result.user_id != current_user.id:
            return jsonify({
                'success': False,
                'error': 'Access denied'
            }), 403
        
        # Get age information and recommendations
        try:
            age_info = persistence_service.get_analysis_age_info(analysis_result)
            logging.info(f"Age info for {analysis_id}: {age_info}")
        except Exception as e:
            logging.error(f"Error getting age info for {analysis_id}: {e}")
            age_info = {'relative_age': 'Unknown', 'staleness_level': 'fresh'}
        
        try:
            refresh_recommendations = persistence_service.get_refresh_recommendations(analysis_result)
        except Exception as e:
            logging.error(f"Error getting refresh recommendations for {analysis_id}: {e}")
            refresh_recommendations = {}
        
        try:
            library_changes = persistence_service.get_library_change_summary(analysis_result)
        except Exception as e:
            logging.error(f"Error getting library changes for {analysis_id}: {e}")
            library_changes = {'has_changes': False}
        
        # Convert to duplicate groups for display
        logging.info(f"Converting analysis {analysis_id} to duplicate groups")
        duplicate_groups = persistence_service.convert_to_duplicate_groups(analysis_result)
        logging.info(f"Converted to {len(duplicate_groups)} duplicate groups")
        
        # Get pagination parameters
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
        
        # Apply pagination to groups
        total_groups = len(duplicate_groups)
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        paginated_groups = duplicate_groups[start_index:end_index]
        
        # Convert groups to JSON-serializable format
        serialized_groups = []
        for group in paginated_groups:
            group_dict = {
                'canonical_song': {
                    'id': group.canonical_song.id,
                    'song': group.canonical_song.song,
                    'artist': group.canonical_song.artist,
                    'album': group.canonical_song.album,
                    'play_cnt': group.canonical_song.play_cnt,
                    'last_play_dt': group.canonical_song.last_play_dt.isoformat() if group.canonical_song.last_play_dt else None,
                    'date_added': group.canonical_song.date_added.isoformat() if group.canonical_song.date_added else None
                },
                'duplicates': [],
                'similarity_scores': group.similarity_scores,
                'suggested_action': group.suggested_action
            }
            
            # Add duplicates
            for duplicate in group.duplicates:
                group_dict['duplicates'].append({
                    'id': duplicate.id,
                    'song': duplicate.song,
                    'artist': duplicate.artist,
                    'album': duplicate.album,
                    'play_cnt': duplicate.play_cnt,
                    'last_play_dt': duplicate.last_play_dt.isoformat() if duplicate.last_play_dt else None,
                    'date_added': duplicate.date_added.isoformat() if duplicate.date_added else None
                })
            
            serialized_groups.append(group_dict)
        
        return jsonify({
            'success': True,
            'analysis_id': analysis_result.analysis_id,  # Add this for loadAnalysisResults compatibility
            'analysis': {
                'analysis_id': analysis_result.analysis_id,
                'created_at': analysis_result.created_at.isoformat(),
                'completed_at': analysis_result.completed_at.isoformat() if analysis_result.completed_at else None,
                'status': analysis_result.status,
                'search_term': analysis_result.search_term,
                'sort_by': analysis_result.sort_by,
                'min_confidence': analysis_result.min_confidence,
                'total_groups': analysis_result.total_groups_found,
                'total_duplicates': analysis_result.total_duplicates_found,
                'processing_time': analysis_result.processing_time_seconds
            },
            'duplicate_groups': serialized_groups,
            'age_info': age_info,
            'refresh_recommendations': refresh_recommendations,
            'library_changes': library_changes,
            'pagination': {
                'current_page': page,
                'per_page': per_page,
                'total_groups': total_groups,
                'total_pages': (total_groups + per_page - 1) // per_page,
                'has_prev': page > 1,
                'has_next': end_index < total_groups
            }
        })
        
    except Exception as e:
        logging.error(f"Error getting analysis {analysis_id}: {e}")
        logging.error(f"Full traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/duplicates/analysis/<analysis_id>/age-check')
@login_required
def check_analysis_age(analysis_id):
    """Check if analysis is stale and provide refresh recommendations."""
    try:
        # Initialize persistence service
        persistence_service = DuplicatePersistenceService()
        
        # Load the analysis result
        analysis_result = persistence_service.load_analysis_result(analysis_id)
        
        if not analysis_result:
            return jsonify({
                'success': False,
                'error': 'Analysis not found'
            }), 404
        
        # Security check - ensure user owns this analysis
        if analysis_result.user_id != current_user.id:
            return jsonify({
                'success': False,
                'error': 'Access denied'
            }), 403
        
        # Get staleness information
        is_stale = persistence_service.is_analysis_stale(analysis_result)
        staleness_level = persistence_service.get_staleness_level(analysis_result)
        age_info = persistence_service.get_analysis_age_info(analysis_result)
        refresh_recommendations = persistence_service.get_refresh_recommendations(analysis_result)
        library_changes = persistence_service.get_library_change_summary(analysis_result)
        
        return jsonify({
            'success': True,
            'analysis_id': analysis_id,
            'is_stale': is_stale,
            'staleness_level': staleness_level,
            'age_info': age_info,
            'refresh_recommendations': refresh_recommendations,
            'library_changes': library_changes
        })
        
    except Exception as e:
        logging.error(f"Error checking analysis age for {analysis_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/duplicates/analysis/<analysis_id>/library-changes')
@login_required
def get_library_changes(analysis_id):
    """Get summary of library changes since analysis was performed."""
    try:
        # Initialize persistence service
        persistence_service = DuplicatePersistenceService()
        
        # Load the analysis result
        analysis_result = persistence_service.load_analysis_result(analysis_id)
        
        if not analysis_result:
            return jsonify({
                'success': False,
                'error': 'Analysis not found'
            }), 404
        
        # Security check - ensure user owns this analysis
        if analysis_result.user_id != current_user.id:
            return jsonify({
                'success': False,
                'error': 'Access denied'
            }), 403
        
        # Get detailed library change information
        library_changes = persistence_service.get_library_change_summary(analysis_result)
        
        # Get additional context about the changes
        change_details = {
            'analysis_date': analysis_result.created_at.isoformat(),
            'analysis_track_count': analysis_result.library_track_count,
            'current_track_count': library_changes['current_track_count'],
            'net_change': library_changes['current_track_count'] - (analysis_result.library_track_count or 0),
            'change_percentage': library_changes['change_percentage'],
            'significant_change': library_changes['significant_change'],
            'tracks_added': library_changes['tracks_added'],
            'tracks_modified': library_changes['tracks_modified'],
            'tracks_deleted': library_changes['tracks_deleted'],
            'total_changes': library_changes['total_changes']
        }
        
        # Determine recommendation based on changes
        if library_changes['significant_change']:
            recommendation = {
                'should_refresh': True,
                'reason': 'Significant library changes detected',
                'priority': 'high' if library_changes['change_percentage'] > 20 else 'medium'
            }
        elif library_changes['total_changes'] > 10:
            recommendation = {
                'should_refresh': True,
                'reason': 'Multiple library changes detected',
                'priority': 'medium'
            }
        else:
            recommendation = {
                'should_refresh': False,
                'reason': 'Minimal library changes',
                'priority': 'low'
            }
        
        return jsonify({
            'success': True,
            'analysis_id': analysis_id,
            'library_changes': change_details,
            'recommendation': recommendation
        })
        
    except Exception as e:
        logging.error(f"Error getting library changes for {analysis_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/duplicates/analysis/<analysis_id>/refresh', methods=['POST'])
@login_required
def refresh_analysis(analysis_id):
    """Refresh existing analysis with same parameters."""
    try:
        # Initialize services
        persistence_service = DuplicatePersistenceService()
        duplicate_service = DuplicateDetectionService()
        
        # Load the existing analysis to get parameters
        existing_analysis = persistence_service.load_analysis_result(analysis_id)
        
        if not existing_analysis:
            return jsonify({
                'success': False,
                'error': 'Analysis not found'
            }), 404
        
        # Security check - ensure user owns this analysis
        if existing_analysis.user_id != current_user.id:
            return jsonify({
                'success': False,
                'error': 'Access denied'
            }), 403
        
        # Extract parameters from existing analysis
        analysis_params = {
            'search_term': existing_analysis.search_term,
            'sort_by': existing_analysis.sort_by,
            'min_confidence': existing_analysis.min_confidence,
            'user_id': current_user.id,
            'force_refresh': True
        }
        
        # Check if there's already a running analysis for this user
        running_analyses = db.session.query(DuplicateAnalysisResult)\
            .filter(
                DuplicateAnalysisResult.user_id == current_user.id,
                DuplicateAnalysisResult.status == 'running'
            ).count()
        
        if running_analyses > 0:
            return jsonify({
                'success': False,
                'error': 'Another analysis is already running. Please wait for it to complete.'
            }), 409
        
        # Start the refresh analysis
        try:
            result = duplicate_service.find_duplicates_with_persistence(**analysis_params)
            
            return jsonify({
                'success': True,
                'message': 'Analysis refresh started successfully',
                'new_analysis_id': result.get('analysis_id'),
                'original_analysis_id': analysis_id,
                'parameters_used': {
                    'search_term': analysis_params['search_term'],
                    'sort_by': analysis_params['sort_by'],
                    'min_confidence': analysis_params['min_confidence']
                }
            })
            
        except Exception as analysis_error:
            logging.error(f"Error starting refresh analysis: {analysis_error}")
            return jsonify({
                'success': False,
                'error': f'Failed to start analysis refresh: {str(analysis_error)}'
            }), 500
        
    except Exception as e:
        logging.error(f"Error refreshing analysis {analysis_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/duplicates/quick-refresh', methods=['POST'])
@login_required
def quick_refresh():
    """Start new analysis with parameters from most recent analysis."""
    try:
        # Initialize services
        persistence_service = DuplicatePersistenceService()
        duplicate_service = DuplicateDetectionService()
        
        # Get request data for optional parameter overrides
        data = request.get_json() or {}
        
        # Get the most recent analysis for this user
        latest_analysis = persistence_service.get_latest_analysis(current_user.id)
        
        if not latest_analysis:
            # No previous analysis found, use default parameters
            analysis_params = {
                'search_term': data.get('search_term'),
                'sort_by': data.get('sort_by', 'artist'),
                'min_confidence': data.get('min_confidence', 0.0),
                'user_id': current_user.id,
                'force_refresh': True
            }
        else:
            # Use parameters from latest analysis, with optional overrides from request
            analysis_params = {
                'search_term': data.get('search_term', latest_analysis.search_term),
                'sort_by': data.get('sort_by', latest_analysis.sort_by),
                'min_confidence': data.get('min_confidence', latest_analysis.min_confidence),
                'user_id': current_user.id,
                'force_refresh': True
            }
        
        # Check if there's already a running analysis for this user
        running_analyses = db.session.query(DuplicateAnalysisResult)\
            .filter(
                DuplicateAnalysisResult.user_id == current_user.id,
                DuplicateAnalysisResult.status == 'running'
            ).count()
        
        if running_analyses > 0:
            return jsonify({
                'success': False,
                'error': 'Another analysis is already running. Please wait for it to complete.'
            }), 409
        
        # Start the quick refresh analysis
        try:
            result = duplicate_service.find_duplicates_with_persistence(**analysis_params)
            
            return jsonify({
                'success': True,
                'message': 'Quick refresh analysis started successfully',
                'analysis_id': result.get('analysis_id'),
                'based_on_previous': latest_analysis is not None,
                'previous_analysis_id': latest_analysis.analysis_id if latest_analysis else None,
                'parameters_used': {
                    'search_term': analysis_params['search_term'],
                    'sort_by': analysis_params['sort_by'],
                    'min_confidence': analysis_params['min_confidence']
                }
            })
            
        except Exception as analysis_error:
            logging.error(f"Error starting quick refresh analysis: {analysis_error}")
            return jsonify({
                'success': False,
                'error': f'Failed to start quick refresh analysis: {str(analysis_error)}'
            }), 500
        
    except Exception as e:
        logging.error(f"Error in quick refresh: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/duplicates/progress/<analysis_id>')
@login_required
def get_analysis_progress(analysis_id):
    """Get real-time progress of running analysis."""
    try:
        # Initialize services
        duplicate_service = DuplicateDetectionService()
        persistence_service = DuplicatePersistenceService()
        
        # Get progress from duplicate detection service
        progress_info = duplicate_service.get_analysis_progress(analysis_id)
        
        # Debug logging to see what's being returned
        logging.info(f"Progress endpoint called for {analysis_id}: progress_info = {progress_info}")
        
        if not progress_info:
            # Check if analysis exists in database
            analysis_result = persistence_service.load_analysis_result(analysis_id)
            
            if not analysis_result:
                return jsonify({
                    'success': False,
                    'error': 'Analysis not found'
                }), 404
            
            # Security check - ensure user owns this analysis
            if analysis_result.user_id != current_user.id:
                return jsonify({
                    'success': False,
                    'error': 'Access denied'
                }), 403
            
            # Analysis exists but no progress info - likely completed or failed
            return jsonify({
                'success': True,
                'analysis_id': analysis_id,
                'status': analysis_result.status,
                'progress': {
                    'phase': 'completed' if analysis_result.status == 'completed' else analysis_result.status,
                    'percentage': 100 if analysis_result.status == 'completed' else 0,
                    'current_step': 0,
                    'total_steps': 0,
                    'message': f'Analysis {analysis_result.status}',
                    'estimated_remaining_seconds': 0,
                    'tracks_processed': analysis_result.total_tracks_analyzed or 0,
                    'total_tracks': analysis_result.total_tracks_analyzed or 0,
                    'groups_found': analysis_result.total_groups_found or 0
                },
                'completed_at': analysis_result.completed_at.isoformat() if analysis_result.completed_at else None,
                'error_message': analysis_result.error_message
            })
        
        # Security check for active progress
        if progress_info.get('user_id') != current_user.id:
            return jsonify({
                'success': False,
                'error': 'Access denied'
            }), 403
        
        return jsonify({
            'success': True,
            'analysis_id': analysis_id,
            'status': progress_info.get('status', 'running'),
            'progress': {
                'phase': progress_info.get('phase', 'unknown'),
                'percentage': progress_info.get('percentage', 0),
                'current_step': progress_info.get('current_step', 0),
                'total_steps': progress_info.get('total_steps', 0),
                'message': progress_info.get('current_message', ''),
                'estimated_remaining_seconds': progress_info.get('estimated_remaining_seconds'),
                'tracks_processed': progress_info.get('tracks_processed', 0),
                'total_tracks': progress_info.get('total_tracks', 0),
                'groups_found': progress_info.get('groups_found', 0)
            },
            'start_time': progress_info.get('start_time'),
            'last_update': progress_info.get('last_update')
        })
        
    except Exception as e:
        logging.error(f"Error getting analysis progress for {analysis_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/duplicates/analysis/<analysis_id>/cancel', methods=['POST'])
@login_required
def cancel_analysis(analysis_id):
    """Cancel a running analysis with graceful cancellation and partial result preservation."""
    try:
        # Initialize services
        duplicate_service = DuplicateDetectionService()
        persistence_service = DuplicatePersistenceService()
        
        # Check if analysis exists and user has permission
        analysis_result = persistence_service.load_analysis_result(analysis_id)
        
        if not analysis_result:
            return jsonify({
                'success': False,
                'error': 'Analysis not found'
            }), 404
        
        # Security check - ensure user owns this analysis
        if analysis_result.user_id != current_user.id:
            return jsonify({
                'success': False,
                'error': 'Access denied'
            }), 403
        
        # Check if analysis is actually running
        if analysis_result.status not in ['running', 'starting']:
            return jsonify({
                'success': False,
                'error': f'Cannot cancel analysis with status: {analysis_result.status}',
                'current_status': analysis_result.status
            }), 400
        
        # Attempt to cancel the running analysis
        cancellation_result = duplicate_service.cancel_analysis(analysis_id)
        
        if cancellation_result:
            # Update analysis status to cancelled
            success = persistence_service.update_analysis_status(
                analysis_id, 
                'cancelled',
                error_message='Analysis cancelled by user'
            )
            
            if success:
                return jsonify({
                    'success': True,
                    'message': 'Analysis cancelled successfully',
                    'analysis_id': analysis_id,
                    'partial_results_preserved': True,
                    'can_resume': False  # Current implementation doesn't support resume
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Analysis was cancelled but status update failed'
                }), 500
        else:
            # Cancellation failed - analysis might have completed or already been cancelled
            # Refresh the analysis status
            updated_analysis = persistence_service.load_analysis_result(analysis_id)
            
            return jsonify({
                'success': False,
                'error': 'Failed to cancel analysis - it may have already completed',
                'current_status': updated_analysis.status if updated_analysis else 'unknown',
                'analysis_id': analysis_id
            }), 400
        
    except Exception as e:
        logging.error(f"Error cancelling analysis {analysis_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/duplicates/cleanup', methods=['POST'])
@login_required
def cleanup_old_analyses():
    """Clean up old analysis results with user-specific options."""
    try:
        # Get request parameters
        data = request.get_json() or {}
        retention_days = data.get('retention_days', 30)
        max_results_per_user = data.get('max_results_per_user', 5)
        user_only = data.get('user_only', True)  # Only cleanup current user's analyses
        
        # Initialize persistence service
        persistence_service = DuplicatePersistenceService()
        
        if user_only:
            # Custom cleanup for current user only
            try:
                # Get user's analyses ordered by creation date (newest first)
                user_analyses = persistence_service.get_user_analyses(
                    user_id=current_user.id,
                    limit=1000  # Get all analyses for cleanup
                )
                
                cleanup_stats = {
                    'deleted_by_age': 0,
                    'deleted_by_limit': 0,
                    'total_deleted': 0,
                    'errors': 0
                }
                
                # Clean up by age
                from datetime import datetime, timedelta
                cutoff_date = datetime.now() - timedelta(days=retention_days)
                
                for analysis in user_analyses:
                    if analysis.created_at < cutoff_date:
                        try:
                            success = persistence_service.delete_analysis_result(
                                analysis.analysis_id, 
                                current_user.id
                            )
                            if success:
                                cleanup_stats['deleted_by_age'] += 1
                            else:
                                cleanup_stats['errors'] += 1
                        except Exception as e:
                            cleanup_stats['errors'] += 1
                            logging.error(f"Error deleting analysis {analysis.analysis_id}: {e}")
                
                # Clean up by limit (keep only the most recent analyses)
                remaining_analyses = [a for a in user_analyses if a.created_at >= cutoff_date]
                if len(remaining_analyses) > max_results_per_user:
                    excess_analyses = remaining_analyses[max_results_per_user:]
                    for analysis in excess_analyses:
                        try:
                            success = persistence_service.delete_analysis_result(
                                analysis.analysis_id, 
                                current_user.id
                            )
                            if success:
                                cleanup_stats['deleted_by_limit'] += 1
                            else:
                                cleanup_stats['errors'] += 1
                        except Exception as e:
                            cleanup_stats['errors'] += 1
                            logging.error(f"Error deleting excess analysis {analysis.analysis_id}: {e}")
                
                cleanup_stats['total_deleted'] = cleanup_stats['deleted_by_age'] + cleanup_stats['deleted_by_limit']
                
            except Exception as e:
                logging.error(f"Error in user-specific cleanup: {e}")
                return jsonify({
                    'success': False,
                    'error': f'Cleanup failed: {str(e)}'
                }), 500
        else:
            # System-wide cleanup (admin only)
            # For now, restrict this to user-only cleanup for security
            return jsonify({
                'success': False,
                'error': 'System-wide cleanup not available in this version'
            }), 403
        
        return jsonify({
            'success': True,
            'message': f'Cleanup completed successfully',
            'cleanup_stats': cleanup_stats,
            'parameters_used': {
                'retention_days': retention_days,
                'max_results_per_user': max_results_per_user,
                'user_only': user_only
            }
        })
        
    except Exception as e:
        logging.error(f"Error in cleanup operation: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# Export functionality routes

@admin_bp.route('/duplicates/analysis/<analysis_id>/export', methods=['POST'])
@login_required
def export_analysis(analysis_id):
    """Export analysis results to CSV/JSON with format selection and progress tracking."""
    try:
        # Get export parameters
        data = request.get_json() or {}
        export_format = data.get('format', 'json').lower()
        
        # Validate format
        if export_format not in ['json', 'csv']:
            return jsonify({
                'success': False,
                'error': 'Invalid export format. Must be "json" or "csv"'
            }), 400
        
        # Initialize persistence service
        persistence_service = DuplicatePersistenceService()
        
        # Progress tracking callback
        progress_data = {'current': 0, 'total': 100, 'message': 'Starting export...'}
        
        def progress_callback(message, current, total):
            progress_data.update({
                'message': message,
                'current': current,
                'total': total
            })
            logging.info(f"Export progress: {message} ({current}/{total})")
        
        # Export analysis results
        export_result = persistence_service.export_analysis_results(
            analysis_id=analysis_id,
            format=export_format,
            user_id=current_user.id,
            progress_callback=progress_callback
        )
        
        if export_result['success']:
            return jsonify({
                'success': True,
                'export_id': export_result['export_id'],
                'filename': export_result['filename'],
                'format': export_result['format'],
                'file_size': export_result['file_size'],
                'file_size_mb': export_result['file_size_mb'],
                'total_groups': export_result['total_groups'],
                'total_tracks': export_result['total_tracks'],
                'expires_at': export_result['expires_at'],
                'message': f'Export completed successfully. File size: {export_result["file_size_mb"]} MB'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Export failed'
            }), 500
            
    except Exception as e:
        logging.error(f"Error exporting analysis {analysis_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/duplicates/export/<export_id>/download')
@login_required
def download_export(export_id):
    """Download exported analysis file with user authorization checks."""
    try:
        # Initialize persistence service
        persistence_service = DuplicatePersistenceService()
        
        # Get export record with user authorization
        export_record = persistence_service.get_export_by_id(export_id, current_user.id)
        
        if not export_record:
            abort(404, description="Export not found or access denied")
        
        # Check if export has expired
        if export_record.expires_at and export_record.expires_at < datetime.now():
            return jsonify({
                'success': False,
                'error': 'Export has expired'
            }), 410  # Gone
        
        # Check if file exists
        if not export_record.file_path or not os.path.exists(export_record.file_path):
            return jsonify({
                'success': False,
                'error': 'Export file not found'
            }), 404
        
        # Mark as downloaded
        persistence_service.mark_export_downloaded(export_id, current_user.id)
        
        # Send file
        return send_file(
            export_record.file_path,
            as_attachment=True,
            download_name=export_record.filename,
            mimetype='application/octet-stream'
        )
        
    except Exception as e:
        logging.error(f"Error downloading export {export_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/duplicates/exports')
@login_required
def list_exports():
    """List export history with file size and format information."""
    try:
        # Get pagination parameters
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 10)), 50)  # Max 50 per page
        analysis_id = request.args.get('analysis_id')  # Optional filter
        
        # Initialize persistence service
        persistence_service = DuplicatePersistenceService()
        
        # Get export history
        offset = (page - 1) * per_page
        exports = persistence_service.get_export_history(
            user_id=current_user.id,
            analysis_id=analysis_id,
            limit=per_page,
            offset=offset
        )
        
        # Convert to JSON-serializable format
        export_list = []
        for export in exports:
            export_data = {
                'export_id': export.export_id,
                'analysis_id': export.analysis_id,
                'format': export.format,
                'filename': export.filename,
                'file_size': export.file_size,
                'file_size_mb': round(export.file_size / (1024 * 1024), 2),
                'created_at': export.created_at.isoformat(),
                'status': export.status,
                'download_count': export.download_count,
                'last_downloaded_at': export.last_downloaded_at.isoformat() if export.last_downloaded_at else None,
                'expires_at': export.expires_at.isoformat() if export.expires_at else None,
                'expired': export.expires_at < datetime.now() if export.expires_at else False
            }
            export_list.append(export_data)
        
        # Get export statistics
        stats = persistence_service.get_export_statistics(current_user.id, days=30)
        
        return jsonify({
            'success': True,
            'exports': export_list,
            'pagination': {
                'current_page': page,
                'per_page': per_page,
                'has_more': len(exports) == per_page
            },
            'statistics': stats,
            'filters': {
                'analysis_id': analysis_id
            }
        })
        
    except Exception as e:
        logging.error(f"Error listing exports: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/duplicates/export/<export_id>', methods=['DELETE'])
@login_required
def delete_export(export_id):
    """Delete an export record and its associated file."""
    try:
        # Initialize persistence service
        persistence_service = DuplicatePersistenceService()
        
        # Delete export with user authorization
        success = persistence_service.delete_export(export_id, current_user.id)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Export deleted successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Export not found or access denied'
            }), 404
            
    except Exception as e:
        logging.error(f"Error deleting export {export_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/duplicates/exports/cleanup', methods=['POST'])
@login_required
def cleanup_exports():
    """Clean up expired export files and database records."""
    try:
        # Initialize persistence service
        persistence_service = DuplicatePersistenceService()
        
        # Clean up expired exports
        cleanup_stats = persistence_service.cleanup_expired_exports()
        
        return jsonify({
            'success': True,
            'message': 'Export cleanup completed successfully',
            'cleanup_stats': cleanup_stats
        })
        
    except Exception as e:
        logging.error(f"Error cleaning up exports: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/duplicates/export/<export_id>/progress')
@login_required
def get_export_progress(export_id):
    """Get export progress for large datasets (placeholder for future async implementation)."""
    try:
        # Initialize persistence service
        persistence_service = DuplicatePersistenceService()
        
        # Get progress (currently synchronous, so always completed)
        progress = persistence_service.get_export_progress(export_id)
        
        return jsonify({
            'success': True,
            'progress': progress
        })
        
    except Exception as e:
        logging.error(f"Error getting export progress {export_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# Impact Tracking and Resolution Status Management Routes
# ============================================================================

@admin_bp.route('/duplicates/analysis/<analysis_id>/impact')
@login_required
def get_analysis_impact(analysis_id):
    """Get impact summary showing cleanup progress and remaining duplicates."""
    try:
        from services.duplicate_persistence_service import DuplicatePersistenceService
        persistence_service = DuplicatePersistenceService()
        
        # Get impact summary
        impact_summary = persistence_service.get_impact_summary(analysis_id)
        
        # Get new analysis suggestion
        new_analysis_suggestion = persistence_service.suggest_new_analysis_after_cleanup(analysis_id)
        
        return jsonify({
            'success': True,
            'impact_summary': impact_summary,
            'new_analysis_suggestion': new_analysis_suggestion
        })
        
    except Exception as e:
        error_response = {
            'success': False,
            'error': f'Failed to get analysis impact: {str(e)}'
        }
        return jsonify(error_response), 500


@admin_bp.route('/duplicates/analysis/<analysis_id>/resolution-status', methods=['POST'])
@login_required
def update_resolution_status(analysis_id):
    """Manually update resolution status for duplicate groups."""
    try:
        from services.duplicate_persistence_service import DuplicatePersistenceService
        persistence_service = DuplicatePersistenceService()
        
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        group_ids = data.get('group_ids', [])
        resolution_action = data.get('resolution_action')
        
        if not group_ids or not resolution_action:
            return jsonify({
                'success': False,
                'error': 'Group IDs and resolution action are required'
            }), 400
        
        # Validate resolution action
        valid_actions = ['deleted', 'kept_canonical', 'manual_review', 'duplicates_deleted', 'all_deleted']
        if resolution_action not in valid_actions:
            return jsonify({
                'success': False,
                'error': f'Invalid resolution action. Must be one of: {valid_actions}'
            }), 400
        
        # Update resolution status
        resolved_count = persistence_service.mark_groups_resolved(
            group_ids, 
            resolution_action, 
            user_id=current_user.id
        )
        
        return jsonify({
            'success': True,
            'message': f'Updated resolution status for {resolved_count} groups',
            'resolved_count': resolved_count,
            'resolution_action': resolution_action
        })
        
    except Exception as e:
        error_response = {
            'success': False,
            'error': f'Failed to update resolution status: {str(e)}'
        }
        return jsonify(error_response), 500


@admin_bp.route('/duplicates/cleanup-history')
@login_required
def get_cleanup_history():
    """Get cleanup history and progress tracking showing duplicate management effectiveness over time."""
    try:
        from services.duplicate_persistence_service import DuplicatePersistenceService
        persistence_service = DuplicatePersistenceService()
        
        # Get query parameters
        days_back = request.args.get('days_back', 30, type=int)
        
        # Validate days_back parameter
        if days_back < 1 or days_back > 365:
            return jsonify({
                'success': False,
                'error': 'days_back must be between 1 and 365'
            }), 400
        
        # Get cleanup history
        cleanup_history = persistence_service.get_cleanup_history_summary(
            user_id=current_user.id,
            days_back=days_back
        )
        
        return jsonify({
            'success': True,
            'cleanup_history': cleanup_history
        })
        
    except Exception as e:
        error_response = {
            'success': False,
            'error': f'Failed to get cleanup history: {str(e)}'
        }
        return jsonify(error_response), 500


@admin_bp.route('/duplicates/resolution-tracking/bulk-update', methods=['POST'])
@login_required
def bulk_update_resolution_tracking():
    """Bulk update resolution tracking for multiple deleted tracks."""
    try:
        from services.duplicate_persistence_service import DuplicatePersistenceService
        persistence_service = DuplicatePersistenceService()
        
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        deleted_track_ids = data.get('deleted_track_ids', [])
        
        if not deleted_track_ids:
            return jsonify({
                'success': False,
                'error': 'Deleted track IDs are required'
            }), 400
        
        # Validate track IDs
        try:
            validated_ids = [int(track_id) for track_id in deleted_track_ids]
        except (ValueError, TypeError):
            return jsonify({
                'success': False,
                'error': 'All track IDs must be valid integers'
            }), 400
        
        # Update resolution status
        resolution_update = persistence_service.update_resolution_status_on_track_deletion(
            validated_ids,
            user_id=current_user.id
        )
        
        return jsonify({
            'success': True,
            'message': f'Updated resolution tracking for {resolution_update["updated_tracks"]} tracks in {resolution_update["updated_groups"]} groups',
            'resolution_update': resolution_update
        })
        
    except Exception as e:
        error_response = {
            'success': False,
            'error': f'Failed to bulk update resolution tracking: {str(e)}'
        }
        return jsonify(error_response), 500


@admin_bp.route('/duplicates/analysis/<analysis_id>/suggest-new-analysis')
@login_required
def suggest_new_analysis_after_cleanup(analysis_id):
    """Get suggestion for running new analysis after significant cleanup."""
    try:
        from services.duplicate_persistence_service import DuplicatePersistenceService
        persistence_service = DuplicatePersistenceService()
        
        # Get cleanup threshold from query parameters
        cleanup_threshold = request.args.get('threshold', 20.0, type=float)
        
        # Validate threshold
        if cleanup_threshold < 0 or cleanup_threshold > 100:
            return jsonify({
                'success': False,
                'error': 'Cleanup threshold must be between 0 and 100'
            }), 400
        
        # Get suggestion
        suggestion = persistence_service.suggest_new_analysis_after_cleanup(
            analysis_id,
            cleanup_threshold_percentage=cleanup_threshold
        )
        
        return jsonify({
            'success': True,
            'suggestion': suggestion
        })
        
    except Exception as e:
        error_response = {
            'success': False,
            'error': f'Failed to get new analysis suggestion: {str(e)}'
        }
        return jsonify(error_response), 500


@admin_bp.route('/duplicates/cleanup-audit-trail')
@login_required
def get_cleanup_audit_trail():
    """Get cleanup action audit trail with timestamps and user information."""
    try:
        from services.duplicate_persistence_service import DuplicatePersistenceService
        persistence_service = DuplicatePersistenceService()
        
        # Get query parameters
        days_back = request.args.get('days_back', 30, type=int)
        analysis_id = request.args.get('analysis_id')
        action_type = request.args.get('action_type')
        
        # Validate parameters
        if days_back < 1 or days_back > 365:
            return jsonify({
                'success': False,
                'error': 'days_back must be between 1 and 365'
            }), 400
        
        # Get audit trail
        audit_trail = persistence_service.get_cleanup_audit_trail(
            user_id=current_user.id,
            days_back=days_back,
            analysis_id=analysis_id,
            action_type=action_type
        )
        
        return jsonify({
            'success': True,
            'audit_trail': audit_trail,
            'total_entries': len(audit_trail)
        })
        
    except Exception as e:
        error_response = {
            'success': False,
            'error': f'Failed to get cleanup audit trail: {str(e)}'
        }
        return jsonify(error_response), 500


@admin_bp.route('/duplicates/effectiveness-stats')
@login_required
def get_effectiveness_stats():
    """Get summary statistics showing duplicate management effectiveness over time."""
    try:
        from services.duplicate_persistence_service import DuplicatePersistenceService
        persistence_service = DuplicatePersistenceService()
        
        # Get query parameters
        days_back = request.args.get('days_back', 90, type=int)
        
        # Validate parameters
        if days_back < 1 or days_back > 365:
            return jsonify({
                'success': False,
                'error': 'days_back must be between 1 and 365'
            }), 400
        
        # Get effectiveness statistics
        effectiveness_stats = persistence_service.get_duplicate_management_effectiveness_stats(
            user_id=current_user.id,
            days_back=days_back
        )
        
        return jsonify({
            'success': True,
            'effectiveness_stats': effectiveness_stats
        })
        
    except Exception as e:
        error_response = {
            'success': False,
            'error': f'Failed to get effectiveness stats: {str(e)}'
        }
        return jsonify(error_response), 500


@admin_bp.route('/duplicates/pattern-recommendations')
@login_required
def get_pattern_recommendations():
    """Get recommendations for additional cleanup based on resolution patterns."""
    try:
        from services.duplicate_persistence_service import DuplicatePersistenceService
        persistence_service = DuplicatePersistenceService()
        
        # Get query parameters
        days_back = request.args.get('days_back', 30, type=int)
        
        # Validate parameters
        if days_back < 1 or days_back > 365:
            return jsonify({
                'success': False,
                'error': 'days_back must be between 1 and 365'
            }), 400
        
        # Get pattern-based recommendations
        recommendations = persistence_service.get_cleanup_recommendations_based_on_patterns(
            user_id=current_user.id,
            days_back=days_back
        )
        
        return jsonify({
            'success': True,
            'recommendations': recommendations,
            'total_recommendations': len(recommendations)
        })
        
    except Exception as e:
        error_response = {
            'success': False,
            'error': f'Failed to get pattern recommendations: {str(e)}'
        }
        return jsonify(error_response), 500