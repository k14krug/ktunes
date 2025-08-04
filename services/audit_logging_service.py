"""
Audit Logging Service for tracking administrative actions in the duplicate management system.

This service provides comprehensive logging of all administrative actions including
deletions, bulk operations, and system changes with detailed context and error tracking.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from flask import request, current_app
from flask_login import current_user
from models import AdminAuditLog, Track, User
from extensions import db
from sqlalchemy.exc import SQLAlchemyError
import json


class AuditLoggingService:
    """Service for logging administrative actions with detailed context."""
    
    # Action types for consistent logging
    ACTION_TYPES = {
        'DELETE_DUPLICATE': 'delete_duplicate',
        'BULK_DELETE': 'bulk_delete',
        'SMART_DELETE': 'smart_delete',
        'CACHE_CLEAR': 'cache_clear',
        'PERFORMANCE_OPTIMIZE': 'performance_optimize',
        'ITUNES_VALIDATION': 'itunes_validation',
        'ERROR_RECOVERY': 'error_recovery'
    }
    
    def __init__(self):
        """Initialize the audit logging service."""
        self.logger = logging.getLogger(__name__)
    
    def log_action(self, action_type: str, details: Dict[str, Any], 
                   affected_tracks: int = 0, success: bool = True, 
                   error_message: Optional[str] = None) -> Optional[AdminAuditLog]:
        """
        Log an administrative action with full context.
        
        Args:
            action_type: Type of action performed (use ACTION_TYPES constants)
            details: Dictionary with action-specific details
            affected_tracks: Number of tracks affected by the action
            success: Whether the action was successful
            error_message: Error message if action failed
            
        Returns:
            AdminAuditLog instance if successful, None if logging failed
        """
        try:
            # Get user context
            user_id = None
            if current_user and current_user.is_authenticated:
                user_id = current_user.id
            
            # Get request context
            ip_address = None
            user_agent = None
            if request:
                ip_address = self._get_client_ip()
                user_agent = request.headers.get('User-Agent', '')[:500]  # Limit length
            
            # Sanitize details to ensure JSON serialization
            sanitized_details = self._sanitize_details(details)
            
            # Create audit log entry
            audit_log = AdminAuditLog(
                action_type=action_type,
                user_id=user_id,
                timestamp=datetime.utcnow(),
                details=sanitized_details,
                affected_tracks=affected_tracks,
                success=success,
                error_message=error_message[:1000] if error_message else None,  # Limit length
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            db.session.add(audit_log)
            db.session.commit()
            
            # Also log to application logger
            log_level = logging.INFO if success else logging.ERROR
            log_message = f"Admin action: {action_type} - {affected_tracks} tracks affected"
            if error_message:
                log_message += f" - Error: {error_message}"
            
            self.logger.log(log_level, log_message, extra={
                'action_type': action_type,
                'user_id': user_id,
                'affected_tracks': affected_tracks,
                'success': success,
                'details': sanitized_details
            })
            
            return audit_log
            
        except Exception as e:
            # Fallback logging if database logging fails
            self.logger.error(f"Failed to log audit action {action_type}: {e}", extra={
                'action_type': action_type,
                'affected_tracks': affected_tracks,
                'success': success,
                'original_error': error_message
            })
            return None
    
    def log_duplicate_deletion(self, track_info: Dict[str, Any], 
                             success: bool = True, error_message: Optional[str] = None) -> Optional[AdminAuditLog]:
        """
        Log individual duplicate track deletion.
        
        Args:
            track_info: Dictionary with track information
            success: Whether deletion was successful
            error_message: Error message if deletion failed
            
        Returns:
            AdminAuditLog instance if successful, None if logging failed
        """
        details = {
            'track_id': track_info.get('id'),
            'song': track_info.get('song', 'Unknown'),
            'artist': track_info.get('artist', 'Unknown'),
            'album': track_info.get('album', 'Unknown'),
            'play_count': track_info.get('play_cnt', 0),
            'deletion_reason': 'duplicate_management'
        }
        
        return self.log_action(
            action_type=self.ACTION_TYPES['DELETE_DUPLICATE'],
            details=details,
            affected_tracks=1,
            success=success,
            error_message=error_message
        )
    
    def log_bulk_deletion(self, deleted_tracks: List[Dict[str, Any]], 
                         deletion_strategy: Optional[str] = None,
                         success: bool = True, error_message: Optional[str] = None) -> Optional[AdminAuditLog]:
        """
        Log bulk deletion operation.
        
        Args:
            deleted_tracks: List of deleted track information
            deletion_strategy: Strategy used for bulk deletion
            success: Whether deletion was successful
            error_message: Error message if deletion failed
            
        Returns:
            AdminAuditLog instance if successful, None if logging failed
        """
        details = {
            'deletion_strategy': deletion_strategy or 'manual_selection',
            'total_tracks': len(deleted_tracks),
            'total_play_count': sum(track.get('play_cnt', 0) for track in deleted_tracks),
            'track_summary': [
                {
                    'id': track.get('id'),
                    'song': track.get('song', 'Unknown'),
                    'artist': track.get('artist', 'Unknown'),
                    'play_count': track.get('play_cnt', 0)
                }
                for track in deleted_tracks[:10]  # Limit to first 10 for storage efficiency
            ]
        }
        
        if len(deleted_tracks) > 10:
            details['additional_tracks'] = len(deleted_tracks) - 10
        
        action_type = (self.ACTION_TYPES['SMART_DELETE'] if deletion_strategy 
                      else self.ACTION_TYPES['BULK_DELETE'])
        
        return self.log_action(
            action_type=action_type,
            details=details,
            affected_tracks=len(deleted_tracks),
            success=success,
            error_message=error_message
        )
    
    def log_error_recovery(self, error_type: str, recovery_action: str, 
                          context: Dict[str, Any]) -> Optional[AdminAuditLog]:
        """
        Log error recovery actions.
        
        Args:
            error_type: Type of error that occurred
            recovery_action: Action taken to recover
            context: Additional context about the error and recovery
            
        Returns:
            AdminAuditLog instance if successful, None if logging failed
        """
        details = {
            'error_type': error_type,
            'recovery_action': recovery_action,
            'context': context,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return self.log_action(
            action_type=self.ACTION_TYPES['ERROR_RECOVERY'],
            details=details,
            affected_tracks=0,
            success=True
        )
    
    def log_itunes_validation(self, validation_result: Dict[str, Any]) -> Optional[AdminAuditLog]:
        """
        Log iTunes library validation results.
        
        Args:
            validation_result: Results from iTunes validation
            
        Returns:
            AdminAuditLog instance if successful, None if logging failed
        """
        details = {
            'validation_result': validation_result,
            'xml_path': validation_result.get('xml_path'),
            'total_tracks': validation_result.get('total_tracks', 0),
            'errors': validation_result.get('errors', []),
            'warnings': validation_result.get('warnings', [])
        }
        
        success = validation_result.get('valid', False)
        error_message = '; '.join(validation_result.get('errors', [])) if not success else None
        
        return self.log_action(
            action_type=self.ACTION_TYPES['ITUNES_VALIDATION'],
            details=details,
            affected_tracks=0,
            success=success,
            error_message=error_message
        )
    
    def get_recent_actions(self, limit: int = 50, action_type: Optional[str] = None,
                          user_id: Optional[int] = None, 
                          since: Optional[datetime] = None) -> List[AdminAuditLog]:
        """
        Get recent audit log entries with filtering.
        
        Args:
            limit: Maximum number of entries to return
            action_type: Filter by specific action type
            user_id: Filter by specific user
            since: Only return entries since this datetime
            
        Returns:
            List of AdminAuditLog entries
        """
        try:
            query = AdminAuditLog.query
            
            if action_type:
                query = query.filter(AdminAuditLog.action_type == action_type)
            
            if user_id:
                query = query.filter(AdminAuditLog.user_id == user_id)
            
            if since:
                query = query.filter(AdminAuditLog.timestamp >= since)
            
            return query.order_by(AdminAuditLog.timestamp.desc()).limit(limit).all()
            
        except Exception as e:
            self.logger.error(f"Error retrieving audit logs: {e}")
            return []
    
    def get_action_statistics(self, days: int = 30) -> Dict[str, Any]:
        """
        Get statistics about administrative actions over the specified period.
        
        Args:
            days: Number of days to analyze
            
        Returns:
            Dictionary with action statistics
        """
        try:
            since = datetime.utcnow() - timedelta(days=days)
            
            # Get all actions in the period
            actions = AdminAuditLog.query.filter(
                AdminAuditLog.timestamp >= since
            ).all()
            
            # Calculate statistics
            stats = {
                'total_actions': len(actions),
                'successful_actions': sum(1 for a in actions if a.success),
                'failed_actions': sum(1 for a in actions if not a.success),
                'total_tracks_affected': sum(a.affected_tracks for a in actions),
                'actions_by_type': {},
                'actions_by_day': {},
                'most_active_users': {},
                'error_summary': {}
            }
            
            # Group by action type
            for action in actions:
                action_type = action.action_type
                if action_type not in stats['actions_by_type']:
                    stats['actions_by_type'][action_type] = {
                        'count': 0,
                        'tracks_affected': 0,
                        'success_rate': 0
                    }
                
                stats['actions_by_type'][action_type]['count'] += 1
                stats['actions_by_type'][action_type]['tracks_affected'] += action.affected_tracks
            
            # Calculate success rates
            for action_type, data in stats['actions_by_type'].items():
                type_actions = [a for a in actions if a.action_type == action_type]
                successful = sum(1 for a in type_actions if a.success)
                data['success_rate'] = (successful / len(type_actions)) * 100 if type_actions else 0
            
            # Group by day
            for action in actions:
                day_key = action.timestamp.date().isoformat()
                if day_key not in stats['actions_by_day']:
                    stats['actions_by_day'][day_key] = 0
                stats['actions_by_day'][day_key] += 1
            
            # Most active users
            for action in actions:
                if action.user_id:
                    if action.user_id not in stats['most_active_users']:
                        stats['most_active_users'][action.user_id] = 0
                    stats['most_active_users'][action.user_id] += 1
            
            # Error summary
            failed_actions = [a for a in actions if not a.success]
            for action in failed_actions:
                error_type = action.action_type
                if error_type not in stats['error_summary']:
                    stats['error_summary'][error_type] = []
                stats['error_summary'][error_type].append({
                    'timestamp': action.timestamp.isoformat(),
                    'error_message': action.error_message,
                    'tracks_affected': action.affected_tracks
                })
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Error calculating action statistics: {e}")
            return {
                'error': str(e),
                'total_actions': 0,
                'successful_actions': 0,
                'failed_actions': 0
            }
    
    def cleanup_old_logs(self, days_to_keep: int = 90) -> int:
        """
        Clean up old audit log entries to prevent database bloat.
        
        Args:
            days_to_keep: Number of days of logs to retain
            
        Returns:
            Number of log entries deleted
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
            
            # Delete old entries
            deleted_count = AdminAuditLog.query.filter(
                AdminAuditLog.timestamp < cutoff_date
            ).delete()
            
            db.session.commit()
            
            self.logger.info(f"Cleaned up {deleted_count} old audit log entries")
            return deleted_count
            
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error cleaning up audit logs: {e}")
            return 0
    
    def _get_client_ip(self) -> Optional[str]:
        """Get the client IP address from the request."""
        if not request:
            return None
        
        # Check for forwarded IP first (in case of proxy/load balancer)
        forwarded_ips = request.headers.get('X-Forwarded-For')
        if forwarded_ips:
            return forwarded_ips.split(',')[0].strip()
        
        # Check other common headers
        real_ip = request.headers.get('X-Real-IP')
        if real_ip:
            return real_ip
        
        # Fall back to remote address
        return request.remote_addr
    
    def _sanitize_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize details dictionary to ensure JSON serialization and remove sensitive data.
        
        Args:
            details: Original details dictionary
            
        Returns:
            Sanitized details dictionary
        """
        def sanitize_value(value):
            """Recursively sanitize values for JSON serialization."""
            if isinstance(value, (str, int, float, bool)) or value is None:
                return value
            elif isinstance(value, datetime):
                return value.isoformat()
            elif isinstance(value, dict):
                return {k: sanitize_value(v) for k, v in value.items()}
            elif isinstance(value, (list, tuple)):
                return [sanitize_value(item) for item in value]
            else:
                # Convert other types to string
                return str(value)
        
        try:
            sanitized = sanitize_value(details)
            
            # Remove or mask sensitive information
            sensitive_keys = ['password', 'token', 'secret', 'key', 'auth']
            if isinstance(sanitized, dict):
                for key in list(sanitized.keys()):
                    if any(sensitive in key.lower() for sensitive in sensitive_keys):
                        sanitized[key] = '[REDACTED]'
            
            # Ensure the result can be JSON serialized
            json.dumps(sanitized)
            return sanitized
            
        except (TypeError, ValueError) as e:
            self.logger.warning(f"Error sanitizing details: {e}")
            return {'error': 'Details could not be serialized', 'original_type': str(type(details))}


# Global instance for easy access
_audit_service = None

def get_audit_service() -> AuditLoggingService:
    """Get the global audit logging service instance."""
    global _audit_service
    if _audit_service is None:
        _audit_service = AuditLoggingService()
    return _audit_service