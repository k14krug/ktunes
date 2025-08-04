"""
Error Handling Service for comprehensive error management in the duplicate management system.

This service provides centralized error handling, recovery mechanisms, and user-friendly
error messages for all duplicate management operations.
"""

import logging
import os
import traceback
from typing import Dict, List, Optional, Any, Tuple, Callable
from datetime import datetime
from functools import wraps
from flask import jsonify, current_app
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, OperationalError
from extensions import db
from services.audit_logging_service import get_audit_service


class ErrorType:
    """Constants for different error types."""
    ITUNES_XML_ACCESS = 'itunes_xml_access'
    DATABASE_ERROR = 'database_error'
    TRANSACTION_ROLLBACK = 'transaction_rollback'
    VALIDATION_ERROR = 'validation_error'
    PERMISSION_ERROR = 'permission_error'
    TIMEOUT_ERROR = 'timeout_error'
    NETWORK_ERROR = 'network_error'
    FILE_SYSTEM_ERROR = 'file_system_error'
    UNKNOWN_ERROR = 'unknown_error'


class RecoveryAction:
    """Constants for recovery actions."""
    RETRY_OPERATION = 'retry_operation'
    ROLLBACK_TRANSACTION = 'rollback_transaction'
    REFRESH_DATA = 'refresh_data'
    CHECK_PERMISSIONS = 'check_permissions'
    VALIDATE_INPUT = 'validate_input'
    CONTACT_ADMIN = 'contact_admin'
    MANUAL_INTERVENTION = 'manual_intervention'


class ErrorHandlingService:
    """Service for comprehensive error handling and recovery."""
    
    def __init__(self):
        """Initialize the error handling service."""
        self.logger = logging.getLogger(__name__)
        self.audit_service = get_audit_service()
        
        # Error message templates
        self.error_messages = {
            ErrorType.ITUNES_XML_ACCESS: {
                'title': 'iTunes Library Access Error',
                'message': 'Unable to access iTunes XML library file.',
                'suggestions': [
                    'Check if the iTunes XML file exists at the configured path',
                    'Verify file permissions allow read access',
                    'Ensure iTunes has exported the library recently',
                    'Try refreshing the iTunes library export'
                ]
            },
            ErrorType.DATABASE_ERROR: {
                'title': 'Database Operation Error',
                'message': 'A database error occurred during the operation.',
                'suggestions': [
                    'The operation has been safely rolled back',
                    'Try the operation again in a few moments',
                    'If the problem persists, contact an administrator',
                    'Check database connectivity and disk space'
                ]
            },
            ErrorType.TRANSACTION_ROLLBACK: {
                'title': 'Transaction Rolled Back',
                'message': 'The operation was cancelled and all changes have been undone.',
                'suggestions': [
                    'No data was modified due to the error',
                    'Review the error details and try again',
                    'Ensure all required data is valid before retrying',
                    'Contact support if the issue continues'
                ]
            },
            ErrorType.VALIDATION_ERROR: {
                'title': 'Input Validation Error',
                'message': 'The provided data failed validation checks.',
                'suggestions': [
                    'Review the highlighted fields for errors',
                    'Ensure all required fields are filled',
                    'Check that numeric values are within valid ranges',
                    'Verify that IDs reference existing records'
                ]
            },
            ErrorType.PERMISSION_ERROR: {
                'title': 'Permission Denied',
                'message': 'You do not have permission to perform this action.',
                'suggestions': [
                    'Contact an administrator for access',
                    'Verify you are logged in with the correct account',
                    'Check if your session has expired',
                    'Ensure you have the required role permissions'
                ]
            },
            ErrorType.TIMEOUT_ERROR: {
                'title': 'Operation Timeout',
                'message': 'The operation took too long and was cancelled.',
                'suggestions': [
                    'Try reducing the scope of the operation',
                    'Use filters to limit the amount of data processed',
                    'Consider breaking large operations into smaller batches',
                    'Check system performance and try again later'
                ]
            }
        }
    
    def handle_error(self, error: Exception, context: Dict[str, Any] = None, 
                    user_facing: bool = True) -> Dict[str, Any]:
        """
        Handle an error with comprehensive logging and user-friendly response.
        
        Args:
            error: The exception that occurred
            context: Additional context about the error
            user_facing: Whether to return user-friendly messages
            
        Returns:
            Dictionary with error information and recovery suggestions
        """
        context = context or {}
        error_type = self._classify_error(error)
        
        # Generate unique error ID for tracking
        error_id = f"ERR_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{id(error) % 10000:04d}"
        
        # Log the error with full context
        self._log_error(error, error_type, error_id, context)
        
        # Audit log the error
        self.audit_service.log_error_recovery(
            error_type=error_type,
            recovery_action=self._get_recovery_action(error_type),
            context={
                'error_id': error_id,
                'error_message': str(error),
                'context': context,
                'traceback': traceback.format_exc()
            }
        )
        
        # Generate user-friendly response
        if user_facing:
            return self._generate_user_response(error, error_type, error_id, context)
        else:
            return {
                'error_id': error_id,
                'error_type': error_type,
                'error_message': str(error),
                'context': context
            }
    
    def handle_itunes_xml_error(self, xml_path: str, error: Exception) -> Dict[str, Any]:
        """
        Handle iTunes XML file access errors with specific diagnostics.
        
        Args:
            xml_path: Path to the iTunes XML file
            error: The exception that occurred
            
        Returns:
            Dictionary with error details and recovery suggestions
        """
        context = {
            'xml_path': xml_path,
            'file_exists': os.path.exists(xml_path) if xml_path else False,
            'file_readable': False,
            'file_size': None,
            'file_modified': None
        }
        
        # Gather diagnostic information
        if xml_path and os.path.exists(xml_path):
            try:
                context['file_readable'] = os.access(xml_path, os.R_OK)
                context['file_size'] = os.path.getsize(xml_path)
                context['file_modified'] = datetime.fromtimestamp(
                    os.path.getmtime(xml_path)
                ).isoformat()
            except Exception as diag_error:
                context['diagnostic_error'] = str(diag_error)
        
        # Handle specific error types
        if isinstance(error, FileNotFoundError):
            suggestions = [
                f'The iTunes XML file was not found at: {xml_path}',
                'Check the iTunes library path in your configuration',
                'Ensure iTunes has exported the library to XML format',
                'Verify the file path is correct and accessible'
            ]
        elif isinstance(error, PermissionError):
            suggestions = [
                'Permission denied accessing the iTunes XML file',
                'Check file permissions and ensure read access',
                'Try running the application with appropriate permissions',
                'Verify the file is not locked by another application'
            ]
        elif isinstance(error, (OSError, IOError)):
            suggestions = [
                'I/O error accessing the iTunes XML file',
                'Check if the file is corrupted or incomplete',
                'Verify sufficient disk space and system resources',
                'Try re-exporting the iTunes library'
            ]
        else:
            suggestions = [
                'Unexpected error accessing iTunes XML file',
                'Check the application logs for detailed error information',
                'Verify the iTunes XML file format is valid',
                'Contact support if the issue persists'
            ]
        
        return {
            'success': False,
            'error_type': ErrorType.ITUNES_XML_ACCESS,
            'error_message': str(error),
            'context': context,
            'suggestions': suggestions,
            'recovery_actions': [
                RecoveryAction.CHECK_PERMISSIONS,
                RecoveryAction.VALIDATE_INPUT,
                RecoveryAction.MANUAL_INTERVENTION
            ]
        }
    
    def handle_database_transaction_error(self, error: Exception, 
                                        operation_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle database transaction errors with automatic rollback.
        
        Args:
            error: The database exception that occurred
            operation_context: Context about the failed operation
            
        Returns:
            Dictionary with error details and rollback confirmation
        """
        rollback_successful = False
        rollback_error = None
        
        # Attempt to rollback the transaction
        try:
            db.session.rollback()
            rollback_successful = True
            self.logger.info("Database transaction rolled back successfully")
        except Exception as rb_error:
            rollback_error = str(rb_error)
            self.logger.error(f"Failed to rollback transaction: {rb_error}")
        
        # Classify the database error
        if isinstance(error, IntegrityError):
            error_subtype = 'integrity_constraint'
            user_message = 'The operation violates database constraints'
            suggestions = [
                'Check for duplicate records or invalid references',
                'Ensure all required fields have valid values',
                'Verify foreign key relationships are correct'
            ]
        elif isinstance(error, OperationalError):
            error_subtype = 'operational_error'
            user_message = 'Database operation failed'
            suggestions = [
                'Check database connectivity',
                'Verify sufficient disk space',
                'Ensure database is not locked by another process'
            ]
        else:
            error_subtype = 'general_database_error'
            user_message = 'An unexpected database error occurred'
            suggestions = [
                'Try the operation again',
                'Check system resources and connectivity',
                'Contact administrator if problem persists'
            ]
        
        context = {
            **operation_context,
            'rollback_successful': rollback_successful,
            'rollback_error': rollback_error,
            'error_subtype': error_subtype,
            'sql_error_code': getattr(error, 'code', None),
            'sql_error_params': getattr(error, 'params', None)
        }
        
        return {
            'success': False,
            'error_type': ErrorType.DATABASE_ERROR,
            'error_message': user_message,
            'technical_details': str(error),
            'context': context,
            'suggestions': suggestions + [
                'All changes have been rolled back' if rollback_successful 
                else 'WARNING: Transaction rollback may have failed'
            ],
            'recovery_actions': [
                RecoveryAction.ROLLBACK_TRANSACTION,
                RecoveryAction.RETRY_OPERATION,
                RecoveryAction.CONTACT_ADMIN
            ]
        }
    
    def with_error_handling(self, operation_name: str, context: Dict[str, Any] = None):
        """
        Decorator for automatic error handling in service methods.
        
        Args:
            operation_name: Name of the operation for logging
            context: Additional context for error handling
            
        Returns:
            Decorator function
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as error:
                    error_context = {
                        'operation_name': operation_name,
                        'function_name': func.__name__,
                        'args_count': len(args),
                        'kwargs_keys': list(kwargs.keys()),
                        **(context or {})
                    }
                    
                    # Handle the error and return appropriate response
                    error_response = self.handle_error(error, error_context, user_facing=True)
                    
                    # For Flask routes, return JSON response
                    if hasattr(func, '__module__') and 'routes' in func.__module__:
                        return jsonify(error_response), 500
                    
                    # For service methods, return the error dict
                    return error_response
            
            return wrapper
        return decorator
    
    def validate_track_deletion(self, track_ids: List[int]) -> Tuple[bool, List[str]]:
        """
        Validate track deletion request and return any warnings.
        
        Args:
            track_ids: List of track IDs to validate for deletion
            
        Returns:
            Tuple of (is_valid, list_of_warnings)
        """
        warnings = []
        
        try:
            from models import Track
            
            # Check if tracks exist
            existing_tracks = Track.query.filter(Track.id.in_(track_ids)).all()
            existing_ids = {track.id for track in existing_tracks}
            missing_ids = set(track_ids) - existing_ids
            
            if missing_ids:
                warnings.append(f"Tracks not found: {list(missing_ids)}")
            
            # Check for highly played tracks
            high_play_tracks = [
                track for track in existing_tracks 
                if (track.play_cnt or 0) > 100
            ]
            
            if high_play_tracks:
                track_names = [f"{track.song} by {track.artist}" for track in high_play_tracks[:3]]
                if len(high_play_tracks) > 3:
                    track_names.append(f"and {len(high_play_tracks) - 3} more")
                warnings.append(f"High play count tracks will be deleted: {', '.join(track_names)}")
            
            # Check for recently added tracks
            recent_tracks = [
                track for track in existing_tracks
                if track.date_added and (datetime.utcnow() - track.date_added).days < 7
            ]
            
            if recent_tracks:
                warnings.append(f"{len(recent_tracks)} recently added tracks will be deleted")
            
            # Validate batch size
            if len(track_ids) > 200:
                warnings.append(f"Large batch size ({len(track_ids)} tracks) - consider smaller batches")
                return False, warnings
            
            return True, warnings
            
        except Exception as error:
            self.logger.error(f"Error validating track deletion: {error}")
            return False, [f"Validation error: {str(error)}"]
    
    def _classify_error(self, error: Exception) -> str:
        """Classify an error into a specific error type."""
        if isinstance(error, (FileNotFoundError, PermissionError, OSError, IOError)):
            return ErrorType.FILE_SYSTEM_ERROR
        elif isinstance(error, SQLAlchemyError):
            return ErrorType.DATABASE_ERROR
        elif isinstance(error, ValueError):
            return ErrorType.VALIDATION_ERROR
        elif isinstance(error, TimeoutError):
            return ErrorType.TIMEOUT_ERROR
        elif 'iTunes' in str(error) or 'XML' in str(error):
            return ErrorType.ITUNES_XML_ACCESS
        else:
            return ErrorType.UNKNOWN_ERROR
    
    def _get_recovery_action(self, error_type: str) -> str:
        """Get the recommended recovery action for an error type."""
        recovery_map = {
            ErrorType.ITUNES_XML_ACCESS: RecoveryAction.CHECK_PERMISSIONS,
            ErrorType.DATABASE_ERROR: RecoveryAction.ROLLBACK_TRANSACTION,
            ErrorType.TRANSACTION_ROLLBACK: RecoveryAction.RETRY_OPERATION,
            ErrorType.VALIDATION_ERROR: RecoveryAction.VALIDATE_INPUT,
            ErrorType.PERMISSION_ERROR: RecoveryAction.CONTACT_ADMIN,
            ErrorType.TIMEOUT_ERROR: RecoveryAction.RETRY_OPERATION,
            ErrorType.FILE_SYSTEM_ERROR: RecoveryAction.CHECK_PERMISSIONS,
            ErrorType.UNKNOWN_ERROR: RecoveryAction.MANUAL_INTERVENTION
        }
        return recovery_map.get(error_type, RecoveryAction.MANUAL_INTERVENTION)
    
    def _log_error(self, error: Exception, error_type: str, error_id: str, 
                   context: Dict[str, Any]) -> None:
        """Log error with full context and traceback."""
        self.logger.error(
            f"Error {error_id} ({error_type}): {str(error)}",
            extra={
                'error_id': error_id,
                'error_type': error_type,
                'context': context,
                'traceback': traceback.format_exc()
            }
        )
    
    def _generate_user_response(self, error: Exception, error_type: str, 
                               error_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate user-friendly error response."""
        error_template = self.error_messages.get(error_type, {
            'title': 'Unexpected Error',
            'message': 'An unexpected error occurred.',
            'suggestions': ['Please try again or contact support']
        })
        
        return {
            'success': False,
            'error_id': error_id,
            'error_type': error_type,
            'title': error_template['title'],
            'message': error_template['message'],
            'suggestions': error_template['suggestions'],
            'technical_details': str(error) if current_app.debug else None,
            'recovery_action': self._get_recovery_action(error_type),
            'timestamp': datetime.utcnow().isoformat()
        }


# Global instance for easy access
_error_service = None

def get_error_service() -> ErrorHandlingService:
    """Get the global error handling service instance."""
    global _error_service
    if _error_service is None:
        _error_service = ErrorHandlingService()
    return _error_service