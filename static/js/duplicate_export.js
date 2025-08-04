/**
 * Duplicate Analysis Export Manager
 * Handles export functionality for duplicate analysis results
 */

class DuplicateExportManager {
    constructor() {
        this.currentAnalysisId = null;
        this.currentExportId = null;
        this.exportInProgress = false;
        
        this.initializeEventListeners();
    }
    
    initializeEventListeners() {
        // Export button click handlers
        document.addEventListener('click', (e) => {
            if (e.target.id === 'cancelExportBtn') {
                this.cancelExport();
            } else if (e.target.id === 'downloadExportBtn') {
                this.downloadCurrentExport();
            } else if (e.target.id === 'cleanupExportsBtn') {
                this.cleanupExpiredExports();
            }
        });
        
        // Modal event handlers
        $('#exportHistoryModal').on('shown.bs.modal', () => {
            this.loadExportHistory();
        });
        
        $('#exportSuccessModal').on('hidden.bs.modal', () => {
            this.currentExportId = null;
        });
    }
    
    /**
     * Set the current analysis ID for export operations
     */
    setAnalysisId(analysisId) {
        this.currentAnalysisId = analysisId;
        
        // Enable/disable export button based on analysis availability
        const exportBtn = document.getElementById('exportBtn');
        if (exportBtn) {
            exportBtn.disabled = !analysisId;
        }
    }
    
    /**
     * Export analysis results in specified format
     */
    async exportAnalysis(format) {
        if (!this.currentAnalysisId) {
            this.showError('No analysis available for export');
            return;
        }
        
        if (this.exportInProgress) {
            this.showError('Export already in progress');
            return;
        }
        
        try {
            this.exportInProgress = true;
            this.showExportProgress(format);
            
            // Start export
            const response = await fetch(`/admin/duplicates/analysis/${this.currentAnalysisId}/export`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ format: format })
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.currentExportId = result.export_id;
                this.hideExportProgress();
                this.showExportSuccess(result);
            } else {
                this.hideExportProgress();
                this.showError(result.error || 'Export failed');
            }
            
        } catch (error) {
            console.error('Export error:', error);
            this.hideExportProgress();
            this.showError('Export failed: ' + error.message);
        } finally {
            this.exportInProgress = false;
        }
    }
    
    /**
     * Show export progress modal
     */
    showExportProgress(format) {
        document.getElementById('exportFormat').textContent = format.toUpperCase();
        document.getElementById('exportProgressText').textContent = 'Preparing export data...';
        document.getElementById('exportProgressBar').style.width = '0%';
        document.getElementById('exportGroups').textContent = '0';
        document.getElementById('exportTracks').textContent = '0';
        
        $('#exportProgressModal').modal('show');
        
        // Simulate progress updates (since exports are currently synchronous)
        this.simulateExportProgress();
    }
    
    /**
     * Simulate export progress for user feedback
     */
    simulateExportProgress() {
        const progressSteps = [
            { progress: 10, text: 'Loading analysis data...' },
            { progress: 30, text: 'Processing duplicate groups...' },
            { progress: 60, text: 'Formatting export data...' },
            { progress: 80, text: 'Generating export file...' },
            { progress: 95, text: 'Finalizing export...' }
        ];
        
        let stepIndex = 0;
        const interval = setInterval(() => {
            if (stepIndex < progressSteps.length && this.exportInProgress) {
                const step = progressSteps[stepIndex];
                document.getElementById('exportProgressBar').style.width = step.progress + '%';
                document.getElementById('exportProgressText').textContent = step.text;
                stepIndex++;
            } else {
                clearInterval(interval);
            }
        }, 500);
    }
    
    /**
     * Hide export progress modal
     */
    hideExportProgress() {
        $('#exportProgressModal').modal('hide');
    }
    
    /**
     * Show export success modal
     */
    showExportSuccess(result) {
        document.getElementById('successExportFormat').textContent = result.format.toUpperCase();
        document.getElementById('successExportSize').textContent = result.file_size_mb + ' MB';
        document.getElementById('successExportGroups').textContent = result.total_groups;
        document.getElementById('successExportTracks').textContent = result.total_tracks;
        
        $('#exportSuccessModal').modal('show');
    }
    
    /**
     * Download the current export
     */
    async downloadCurrentExport() {
        if (!this.currentExportId) {
            this.showError('No export available for download');
            return;
        }
        
        try {
            // Create download link
            const downloadUrl = `/admin/duplicates/export/${this.currentExportId}/download`;
            
            // Create temporary link and trigger download
            const link = document.createElement('a');
            link.href = downloadUrl;
            link.style.display = 'none';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            
            // Close success modal
            $('#exportSuccessModal').modal('hide');
            
        } catch (error) {
            console.error('Download error:', error);
            this.showError('Download failed: ' + error.message);
        }
    }
    
    /**
     * Cancel current export
     */
    cancelExport() {
        if (this.exportInProgress) {
            this.exportInProgress = false;
            this.hideExportProgress();
            this.showInfo('Export cancelled');
        }
    }
    
    /**
     * Show export history modal
     */
    showExportHistory() {
        $('#exportHistoryModal').modal('show');
    }
    
    /**
     * Load export history
     */
    async loadExportHistory() {
        const loadingElement = document.getElementById('exportHistoryLoading');
        const emptyElement = document.getElementById('exportHistoryEmpty');
        const tableBody = document.getElementById('exportHistoryTableBody');
        
        // Show loading
        loadingElement.style.display = 'block';
        emptyElement.style.display = 'none';
        tableBody.innerHTML = '';
        
        try {
            const response = await fetch('/admin/duplicates/exports');
            const result = await response.json();
            
            if (result.success) {
                this.updateExportStatistics(result.statistics);
                this.populateExportHistory(result.exports);
                
                if (result.exports.length === 0) {
                    emptyElement.style.display = 'block';
                }
            } else {
                this.showError(result.error || 'Failed to load export history');
                emptyElement.style.display = 'block';
            }
            
        } catch (error) {
            console.error('Error loading export history:', error);
            this.showError('Failed to load export history');
            emptyElement.style.display = 'block';
        } finally {
            loadingElement.style.display = 'none';
        }
    }
    
    /**
     * Update export statistics display
     */
    updateExportStatistics(stats) {
        document.getElementById('totalExports').textContent = stats.total_exports;
        document.getElementById('totalSize').textContent = stats.total_size_mb + ' MB';
        document.getElementById('totalDownloads').textContent = stats.total_downloads;
        document.getElementById('jsonExports').textContent = stats.format_breakdown.json?.count || 0;
    }
    
    /**
     * Populate export history table
     */
    populateExportHistory(exports) {
        const tableBody = document.getElementById('exportHistoryTableBody');
        tableBody.innerHTML = '';
        
        exports.forEach(exportRecord => {
            const row = this.createExportHistoryRow(exportRecord);
            tableBody.appendChild(row);
        });
    }
    
    /**
     * Create export history table row
     */
    createExportHistoryRow(exportRecord) {
        const row = document.createElement('tr');
        
        // Format date
        const createdDate = new Date(exportRecord.created_at).toLocaleString();
        
        // Status badge
        let statusBadge = '';
        if (exportRecord.expired) {
            statusBadge = '<span class="badge badge-danger">Expired</span>';
        } else {
            statusBadge = '<span class="badge badge-success">Available</span>';
        }
        
        // Format badge
        const formatBadge = exportRecord.format === 'json' 
            ? '<span class="badge badge-info">JSON</span>'
            : '<span class="badge badge-warning">CSV</span>';
        
        // Actions
        let actions = '';
        if (!exportRecord.expired) {
            actions = `
                <button class="btn btn-sm btn-primary" onclick="exportManager.downloadExport('${exportRecord.export_id}')">
                    <i class="fas fa-download"></i>
                </button>
            `;
        }
        actions += `
            <button class="btn btn-sm btn-danger ml-1" onclick="exportManager.deleteExport('${exportRecord.export_id}')">
                <i class="fas fa-trash"></i>
            </button>
        `;
        
        row.innerHTML = `
            <td>${createdDate}</td>
            <td>${formatBadge}</td>
            <td>${exportRecord.file_size_mb} MB</td>
            <td>${exportRecord.download_count}</td>
            <td>${statusBadge}</td>
            <td>${actions}</td>
        `;
        
        return row;
    }
    
    /**
     * Download specific export
     */
    async downloadExport(exportId) {
        try {
            const downloadUrl = `/admin/duplicates/export/${exportId}/download`;
            
            // Create temporary link and trigger download
            const link = document.createElement('a');
            link.href = downloadUrl;
            link.style.display = 'none';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            
            // Refresh export history to update download count
            setTimeout(() => this.loadExportHistory(), 1000);
            
        } catch (error) {
            console.error('Download error:', error);
            this.showError('Download failed: ' + error.message);
        }
    }
    
    /**
     * Delete specific export
     */
    async deleteExport(exportId) {
        if (!confirm('Are you sure you want to delete this export?')) {
            return;
        }
        
        try {
            const response = await fetch(`/admin/duplicates/export/${exportId}`, {
                method: 'DELETE'
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showSuccess('Export deleted successfully');
                this.loadExportHistory(); // Refresh the list
            } else {
                this.showError(result.error || 'Failed to delete export');
            }
            
        } catch (error) {
            console.error('Delete error:', error);
            this.showError('Failed to delete export');
        }
    }
    
    /**
     * Cleanup expired exports
     */
    async cleanupExpiredExports() {
        if (!confirm('Are you sure you want to cleanup all expired exports?')) {
            return;
        }
        
        try {
            const response = await fetch('/admin/duplicates/exports/cleanup', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCSRFToken()
                }
            });
            
            const result = await response.json();
            
            if (result.success) {
                const stats = result.cleanup_stats;
                this.showSuccess(`Cleanup completed: ${stats.files_deleted} files deleted, ${stats.records_deleted} records updated`);
                this.loadExportHistory(); // Refresh the list
            } else {
                this.showError(result.error || 'Cleanup failed');
            }
            
        } catch (error) {
            console.error('Cleanup error:', error);
            this.showError('Cleanup failed');
        }
    }
    
    /**
     * Show error message
     */
    showError(message) {
        // Use existing notification system or create alert
        if (window.showNotification) {
            window.showNotification(message, 'error');
        } else {
            alert('Error: ' + message);
        }
    }
    
    /**
     * Show success message
     */
    showSuccess(message) {
        // Use existing notification system or create alert
        if (window.showNotification) {
            window.showNotification(message, 'success');
        } else {
            alert('Success: ' + message);
        }
    }
    
    /**
     * Show info message
     */
    showInfo(message) {
        // Use existing notification system or create alert
        if (window.showNotification) {
            window.showNotification(message, 'info');
        } else {
            alert('Info: ' + message);
        }
    }
    
    getCSRFToken() {
        // Get CSRF token from meta tag
        return $('meta[name=csrf-token]').attr('content') || '';
    }
}

// Initialize export manager
const exportManager = new DuplicateExportManager();

// Export for global access
window.exportManager = exportManager;

// Integration with existing duplicate manager
document.addEventListener('DOMContentLoaded', function() {
    // Listen for analysis ID updates from duplicate manager
    if (window.duplicateManager) {
        // Hook into existing duplicate manager if available
        const originalSetAnalysisId = window.duplicateManager.setCurrentAnalysisId;
        if (originalSetAnalysisId) {
            window.duplicateManager.setCurrentAnalysisId = function(analysisId) {
                originalSetAnalysisId.call(this, analysisId);
                exportManager.setAnalysisId(analysisId);
            };
        }
        
        // Also check if there's already an analysis ID set
        if (window.duplicateManager.currentAnalysisId) {
            exportManager.setAnalysisId(window.duplicateManager.currentAnalysisId);
        }
    }
    
    // Listen for custom events from duplicate manager
    document.addEventListener('analysisLoaded', function(event) {
        if (event.detail && event.detail.analysisId) {
            exportManager.setAnalysisId(event.detail.analysisId);
        }
    });
    
    document.addEventListener('analysisCleared', function() {
        exportManager.setAnalysisId(null);
    });
});