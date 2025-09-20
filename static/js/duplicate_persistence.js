/**
 * Duplicate Persistence JavaScript
 * Handles age notifications, staleness indicators, and progress tracking
 */

class DuplicatePersistenceManager {
    constructor() {
        this.currentAnalysisId = null;
        this.progressUpdateInterval = null;
        this.analysisHistory = [];
        this.previousResults = null;

        this.initializeEventListeners();
        this.loadAnalysisHistory();
    }

    initializeEventListeners() {
        // Age banner and refresh controls
        $('#quickRefreshBtn').on('click', () => this.quickRefresh());
        $('#refreshForChangesLink').on('click', (e) => {
            e.preventDefault();
            this.quickRefresh();
        });

        // Progress tracking controls
        $('#cancelAnalysisBtn').on('click', () => this.cancelAnalysis());
        $('#returnToPreviousBtn').on('click', () => this.returnToPreviousResults());

        // Analysis history dropdown
        $(document).on('click', '.analysis-history-item', (e) => {
            const analysisId = $(e.currentTarget).data('analysis-id');
            this.loadAnalysis(analysisId);
        });

        // Keyboard shortcuts
        $(document).on('keydown', (e) => {
            // Only handle shortcuts when not typing in input fields
            if ($(e.target).is('input, textarea, select')) return;

            // Ctrl+R or F5 for quick refresh
            if ((e.ctrlKey && e.key === 'r') || e.key === 'F5') {
                e.preventDefault();
                if ($('#quickRefreshBtn').is(':visible')) {
                    this.quickRefresh();
                }
            }

            // Escape to cancel analysis
            if (e.key === 'Escape' && $('#cancelAnalysisBtn').is(':visible')) {
                this.cancelAnalysis();
            }

            // Ctrl+H for analysis history
            if (e.ctrlKey && e.key === 'h') {
                e.preventDefault();
                $('#analysisHistoryDropdown').parent().find('.dropdown-toggle').dropdown('toggle');
            }
        });

        // Add tooltips for better UX
        this.initializeTooltips();
    }

    /**
     * Initialize tooltips for UI elements
     */
    initializeTooltips() {
        // Add tooltips to buttons
        $('#quickRefreshBtn').attr('title', 'Refresh analysis with same parameters (Ctrl+R)');
        $('#cancelAnalysisBtn').attr('title', 'Cancel current analysis (Escape)');
        $('#returnToPreviousBtn').attr('title', 'Return to previous results');

        // Initialize Bootstrap tooltips
        $('[title]').tooltip();
    }

    /**
     * Load and display analysis age information
     */
    async checkAnalysisAge(analysisId) {
        try {
            const response = await fetch('/admin/duplicates/analysis/' + analysisId + '/age-check');
            const data = await response.json();

            if (data.success) {
                this.displayAgeBanner(data);

                // Check for library changes
                if (data.library_changes && data.library_changes.has_changes) {
                    this.displayLibraryChanges(data.library_changes);
                }

                return data;
            } else {
                console.error('Error checking analysis age:', data.error);
                return null;
            }
        } catch (error) {
            console.error('Network error checking analysis age:', error);
            return null;
        }
    }

/**
 * Display the analysis age banner with appropriate styling
 */
displayAgeBanner(ageData) {
    // Handle different age data formats
    const ageText = ageData.age_text || ageData.relative_age;
    const timestamp = ageData.created_at_formatted || ageData.formatted_timestamp;

    if (!ageData || !ageText) {
        console.log('Age data missing or invalid:', ageData);
        return;
    }

    const banner = $('#analysisAgeBanner');
    const ageTextElement = $('#analysisAgeText');
    const timestampElement = $('#analysisTimestamp');

    // Set age text and timestamp
    ageTextElement.text(ageText);
    if (timestamp) {
        timestampElement.text('(Created: ' + timestamp + ')');
    }

    // Apply staleness styling
    banner.removeClass('alert-success alert-warning alert-danger');

    switch (ageData.staleness_level) {
        case 'fresh':
            banner.addClass('alert-success');
            break;
        case 'moderate':
            banner.addClass('alert-warning');
            break;
        case 'stale':
        case 'very_stale':
            banner.addClass('alert-danger');
            break;
        default:
            banner.addClass('alert-info');
    }

    // Add staleness indicator
    const stalenessIndicator = '<span class="staleness-indicator staleness-' + ageData.staleness_level + '"></span>';
    ageTextElement.prepend(stalenessIndicator);

    // Show the banner
    banner.show();
}

/**
 * Display library changes alert
 */
displayLibraryChanges(libraryChanges) {
    const alert = $('#libraryChangesAlert');
    const text = $('#libraryChangesText');

    const changesText = [];
    if (libraryChanges.tracks_added > 0) {
        changesText.push(libraryChanges.tracks_added + ' tracks added');
    }
    if (libraryChanges.tracks_modified > 0) {
        changesText.push(libraryChanges.tracks_modified + ' tracks modified');
    }
    if (libraryChanges.tracks_deleted > 0) {
        changesText.push(libraryChanges.tracks_deleted + ' tracks deleted');
    }

    text.text(changesText.join(', ') + ' since this analysis.');
    alert.show();
}

    /**
     * Load analysis history for the dropdown
     */
    async loadAnalysisHistory() {
    try {
        const response = await fetch('/admin/duplicates/analyses?limit=10');
        const data = await response.json();

        if (data.success) {
            this.analysisHistory = data.analyses;
            this.populateHistoryDropdown();
        }
    } catch (error) {
        console.error('Error loading analysis history:', error);
    }
}

/**
 * Populate the analysis history dropdown
 */
populateHistoryDropdown() {
    const dropdown = $('#analysisHistoryDropdown');
    dropdown.empty();

    if (this.analysisHistory.length === 0) {
        dropdown.append(`
                <div class="dropdown-item-text text-muted">
                    <i class="fas fa-info-circle"></i> No previous analyses found
                </div>
            `);
        return;
    }

    this.analysisHistory.forEach(analysis => {
        const stalenessClass = `staleness-${analysis.age_info.staleness_level}`;
        const item = $(`
                <div class="analysis-history-item" data-analysis-id="${analysis.analysis_id}">
                    <div class="d-flex justify-content-between align-items-start">
                        <div class="flex-grow-1">
                            <div class="analysis-history-meta">
                                <span class="staleness-indicator ${stalenessClass}"></span>
                                <strong>${analysis.age_info.relative_age}</strong>
                            </div>
                            <div class="analysis-history-stats">
                                ${analysis.summary.total_groups} groups, ${analysis.summary.total_duplicates} duplicates
                            </div>
                        </div>
                        <div class="text-right">
                            <small class="text-muted">${analysis.age_info.formatted_date}</small>
                        </div>
                    </div>
                </div>
            `);

        dropdown.append(item);
    });
}

    /**
     * Quick refresh using the same parameters as the current analysis
     */
    async quickRefresh() {
    if (!this.currentAnalysisId) {
        // If no current analysis, perform a new scan
        if (window.duplicateManager) {
            window.duplicateManager.scanForDuplicates();
        }
        return;
    }

    try {
        // Store current results as previous
        this.storePreviousResults();

        // Start refresh
        const response = await fetch(`/admin/duplicates/analysis/${this.currentAnalysisId}/refresh`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCSRFToken()
            }
        });

        const data = await response.json();

        if (data.success) {
            this.currentAnalysisId = data.analysis_id;
            this.startProgressTracking(data.analysis_id);
        } else {
            this.showError('Error starting refresh: ' + (data.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error starting quick refresh:', error);
        this.showError('Network error starting refresh');
    }
}

    /**
     * Load a specific analysis by ID
     */
    async loadAnalysis(analysisId) {
    try {
        // Clear all progress states and modals
        this.clearProgressState();

        const response = await fetch(`/admin/duplicates/analysis/${analysisId}`);
        const data = await response.json();

        if (data.success) {
            this.currentAnalysisId = analysisId;

            // Display age information
            this.displayAgeBanner(data.age_info);

            if (data.library_changes && data.library_changes.has_changes) {
                this.displayLibraryChanges(data.library_changes);
            }

            // Load the duplicate groups into the main interface
            console.log('Loading analysis results into duplicate manager:', data);
            if (window.duplicateManager) {
                console.log('Duplicate manager found, loading results');
                window.duplicateManager.loadAnalysisResults(data);
            } else {
                console.error('window.duplicateManager not found!');
            }
        } else {
            this.showError('Error loading analysis: ' + (data.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error loading analysis:', error);
        this.showError('Network error loading analysis');
    }
}

/**
 * Start progress tracking for an analysis
 */
startProgressTracking(analysisId) {
    // Hide other sections and show progress tracking
    $('#loadingSection').hide();
    $('#duplicateGroupsSection').hide();
    $('#noResultsSection').hide();
    $('#statisticsSection').hide();
    $('#bulkActionsSection').hide();
    $('#progressTrackingSection').show();

    // Reset progress UI to initial state
    this.resetProgressUI();

    // Show return to previous button if we have previous results
    if (this.previousResults) {
        $('#returnToPreviousBtn').show();
    } else {
        $('#returnToPreviousBtn').hide();
    }

    // Start polling for progress updates with exponential backoff on errors
    this.progressUpdateInterval = setInterval(() => {
        this.updateProgress(analysisId);
    }, 2000); // Update every 2 seconds

    // Initial progress update
    this.updateProgress(analysisId);

    // Add visibility change handler to pause updates when tab is not visible
    this.handleVisibilityChange();
}

/**
 * Reset progress UI to initial state
 */
resetProgressUI() {
    // Reset progress bar
    $('#mainProgressBar').css('width', '0%').removeClass('bg-success bg-danger');
    $('#progressPercentageText').text('0%');
    $('#progressTimeRemaining').text('Estimating time...');

    // Reset phase indicators
    $('.progress-phase').removeClass('active completed error');
    $('.progress-phase-status').text('Pending');
    $('.progress-phase-icon i').removeClass('text-primary text-success text-danger').addClass('text-muted');

    // Reset counters
    $('#tracksProcessedCount').text('0');
    $('#groupsFoundCount').text('0');

    // Reset message
    $('#progressCurrentMessage').removeClass('alert-danger alert-warning').addClass('alert-info');
    $('#progressMessageText').text('Initializing analysis...');

    // Reset phase title
    $('#progressPhaseTitle').text('Analyzing Duplicates');
}

/**
 * Handle visibility change to optimize performance
 */
handleVisibilityChange() {
    if (typeof document.hidden !== 'undefined') {
        document.addEventListener('visibilitychange', () => {
            if (this.progressUpdateInterval) {
                if (document.hidden) {
                    // Reduce update frequency when tab is not visible
                    clearInterval(this.progressUpdateInterval);
                    this.progressUpdateInterval = setInterval(() => {
                        this.updateProgress(this.currentAnalysisId);
                    }, 5000); // Update every 5 seconds when hidden
                } else {
                    // Resume normal update frequency when tab becomes visible
                    clearInterval(this.progressUpdateInterval);
                    this.progressUpdateInterval = setInterval(() => {
                        this.updateProgress(this.currentAnalysisId);
                    }, 2000); // Update every 2 seconds when visible
                }
            }
        });
    }
}

    /**
     * Update progress information
     */
    async updateProgress(analysisId) {
    try {
        const response = await fetch(`/admin/duplicates/progress/${analysisId}`);
        const data = await response.json();

        if (data.success) {
            const progress = data.progress;

            // Debug logging to see what status we're receiving
            console.log(`Progress update for ${analysisId}: status=${data.status}, progress.status=${progress.status}`);

            // Update progress bar with smooth animation
            const progressBar = $('#mainProgressBar');
            const currentWidth = parseFloat(progressBar.css('width')) / progressBar.parent().width() * 100;
            const targetWidth = progress.percentage || 0;

            // Animate progress bar if there's a significant change
            if (Math.abs(targetWidth - currentWidth) > 1) {
                progressBar.animate({
                    width: `${targetWidth}%`
                }, 500);
            } else {
                progressBar.css('width', `${targetWidth}%`);
            }

            $('#progressPercentageText').text(`${Math.round(targetWidth)}%`);

            // Update time remaining with better formatting
            if (progress.estimated_remaining_seconds && progress.estimated_remaining_seconds > 0) {
                const timeText = this.formatTimeRemaining(progress.estimated_remaining_seconds);
                $('#progressTimeRemaining').text(`${timeText} remaining`);
            } else if (progress.status === 'completed') {
                $('#progressTimeRemaining').text('Completed!');
            } else {
                $('#progressTimeRemaining').text('Estimating time...');
            }

            // Update phase indicators
            this.updatePhaseIndicators(progress.status);

            // Update phase title
            $('#progressPhaseTitle').text(this.getPhaseTitle(progress.status));

            // Update counters with animation
            this.animateCounter('#tracksProcessedCount', progress.tracks_processed || 0);
            this.animateCounter('#groupsFoundCount', progress.groups_found || 0);

            // Update current message
            $('#progressMessageText').text(progress.current_message || 'Processing...');

            // Update progress bar color based on status
            if (progress.status === 'completed') {
                progressBar.removeClass('progress-bar-striped progress-bar-animated')
                    .addClass('bg-success');
            } else if (progress.status === 'failed') {
                progressBar.removeClass('progress-bar-striped progress-bar-animated')
                    .addClass('bg-danger');
            } else {
                progressBar.addClass('progress-bar-striped progress-bar-animated')
                    .removeClass('bg-success bg-danger');
            }

            // Check if completed
            console.log(`Checking completion: progress.status='${progress.status}', data.status='${data.status}'`);
            if (progress.status === 'completed' || data.status === 'completed') {
                console.log('Analysis completed detected, calling onAnalysisCompleted');
                this.onAnalysisCompleted(analysisId);
            } else if (progress.status === 'failed' || progress.status === 'cancelled') {
                this.onAnalysisError(progress);
            }
        } else {
            console.error('Error getting progress:', data.error);
            // If analysis not found, it might be completed
            if (data.error && data.error.includes('not found')) {
                this.onAnalysisCompleted(analysisId);
            }
        }
    } catch (error) {
        console.error('Error updating progress:', error);
        // Handle network errors gracefully
        $('#progressMessageText').text('Connection error - retrying...');
    }
}

/**
 * Animate counter changes
 */
animateCounter(selector, targetValue) {
    const element = $(selector);
    const currentValue = parseInt(element.text()) || 0;

    if (currentValue !== targetValue) {
        $({ counter: currentValue }).animate({ counter: targetValue }, {
            duration: 500,
            step: function () {
                element.text(Math.ceil(this.counter));
            },
            complete: function () {
                element.text(targetValue);
            }
        });
    }
}

/**
 * Update phase indicators based on current status
 */
updatePhaseIndicators(status) {
    const phases = ['loading', 'analyzing', 'cross-referencing', 'saving'];
    const statusToPhase = {
        'starting': 'loading',
        'loading_tracks': 'loading',
        'analyzing_similarities': 'analyzing',
        'cross_referencing': 'cross-referencing',
        'saving_results': 'saving',
        'completed': 'saving'
    };

    const currentPhase = statusToPhase[status] || 'loading';
    const currentPhaseIndex = phases.indexOf(currentPhase);

    phases.forEach((phase, index) => {
        const element = $(`#phase-${phase}`);
        element.removeClass('active completed error');

        if (index < currentPhaseIndex) {
            element.addClass('completed');
            element.find('.progress-phase-status').text('Completed');
        } else if (index === currentPhaseIndex) {
            element.addClass('active');
            element.find('.progress-phase-status').text('In Progress');
        } else {
            element.find('.progress-phase-status').text('Pending');
        }
    });
}

/**
 * Get user-friendly phase title
 */
getPhaseTitle(status) {
    const titles = {
        'starting': 'Initializing Analysis',
        'loading_tracks': 'Loading Track Data',
        'analyzing_similarities': 'Analyzing Similarities',
        'cross_referencing': 'Cross-referencing iTunes',
        'saving_results': 'Saving Results',
        'completed': 'Analysis Complete'
    };

    return titles[status] || 'Analyzing Duplicates';
}

    /**
     * Handle analysis completion
     */
    async onAnalysisCompleted(analysisId) {
    // Stop progress updates
    if (this.progressUpdateInterval) {
        clearInterval(this.progressUpdateInterval);
        this.progressUpdateInterval = null;
    }

    // Hide progress section
    $('#progressTrackingSection').hide();

    // Try to load the completed analysis, with fallback to page reload
    try {
        console.log('Loading completed analysis:', analysisId);
        await this.loadAnalysis(analysisId);
        console.log('Analysis loaded successfully');

        // Refresh analysis history
        await this.loadAnalysisHistory();

        // Clear previous results
        this.previousResults = null;
        $('#returnToPreviousBtn').hide();
    } catch (error) {
        console.error('Error loading completed analysis:', error);

        // Fallback: Show a success message and reload the page after a short delay
        this.showSuccess('Analysis completed successfully! Reloading results...');

        setTimeout(() => {
            window.location.reload();
        }, 2000);
    }
}

/**
 * Handle analysis error or cancellation
 */
onAnalysisError(progress) {
    // Stop progress updates
    if (this.progressUpdateInterval) {
        clearInterval(this.progressUpdateInterval);
        this.progressUpdateInterval = null;
    }

    // Update UI to show error state
    const isCancel = progress.status === 'cancelled';
    const alertClass = isCancel ? 'alert-warning' : 'alert-danger';
    const iconClass = isCancel ? 'fa-exclamation-triangle' : 'fa-times-circle';
    const message = isCancel ? 'Analysis cancelled by user' : (progress.error_message || 'Analysis failed');

    $('#progressCurrentMessage').removeClass('alert-info alert-warning alert-danger').addClass(alertClass);
    $('#progressMessageText').html(`<i class="fas ${iconClass}"></i> ${message}`);

    // Update progress bar
    const progressBar = $('#mainProgressBar');
    progressBar.removeClass('progress-bar-striped progress-bar-animated');
    if (isCancel) {
        progressBar.addClass('bg-warning');
    } else {
        progressBar.addClass('bg-danger');
    }

    // Update phase indicators to show error
    $('.progress-phase.active').removeClass('active').addClass(isCancel ? 'cancelled' : 'error');
    $(`.progress-phase.${isCancel ? 'cancelled' : 'error'} .progress-phase-status`).text(isCancel ? 'Cancelled' : 'Failed');

    // Update phase title
    $('#progressPhaseTitle').text(isCancel ? 'Analysis Cancelled' : 'Analysis Failed');

    // Show appropriate buttons
    $('#cancelAnalysisBtn').hide();
    if (this.previousResults) {
        $('#returnToPreviousBtn').show();
    }

    // Add retry button for failed analyses
    if (!isCancel) {
        const retryButton = $(`
                <button type="button" class="btn btn-sm btn-primary ml-2" id="retryAnalysisBtn">
                    <i class="fas fa-redo"></i> Retry Analysis
                </button>
            `);
        $('#returnToPreviousBtn').after(retryButton);

        $('#retryAnalysisBtn').on('click', () => {
            this.quickRefresh();
        });
    }
}

    /**
     * Cancel the current analysis
     */
    async cancelAnalysis() {
    if (!this.currentAnalysisId) return;

    try {
        const response = await fetch(`/admin/duplicates/analysis/${this.currentAnalysisId}/cancel`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': this.getCSRFToken()
            }
        });

        const data = await response.json();

        if (data.success) {
            // Stop progress updates
            if (this.progressUpdateInterval) {
                clearInterval(this.progressUpdateInterval);
                this.progressUpdateInterval = null;
            }

            // Update UI
            $('#progressCurrentMessage').removeClass('alert-info').addClass('alert-warning');
            $('#progressMessageText').text('Analysis cancelled by user');

            // Show return to previous button if available
            if (this.previousResults) {
                $('#returnToPreviousBtn').show();
            }
        } else {
            this.showError('Error cancelling analysis: ' + (data.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error cancelling analysis:', error);
        this.showError('Network error cancelling analysis');
    }
}

/**
 * Return to previous results
 */
returnToPreviousResults() {
    if (!this.previousResults) return;

    // Hide progress section
    $('#progressTrackingSection').hide();

    // Restore previous results
    if (window.duplicateManager) {
        window.duplicateManager.loadAnalysisResults(this.previousResults);
    }

    // Clear current analysis
    this.currentAnalysisId = this.previousResults.analysis_id;
    this.previousResults = null;
    $('#returnToPreviousBtn').hide();
}

/**
 * Store current results before starting a refresh
 */
storePreviousResults() {
    if (window.duplicateManager && window.duplicateManager.duplicateGroups) {
        this.previousResults = {
            analysis_id: this.currentAnalysisId,
            duplicate_groups: window.duplicateManager.duplicateGroups,
            // Store other relevant data
        };
    }
}

/**
 * Format time remaining in a user-friendly way
 */
formatTimeRemaining(seconds) {
    if (seconds < 60) {
        return `${Math.round(seconds)}s`;
    } else if (seconds < 3600) {
        const minutes = Math.round(seconds / 60);
        return `${minutes}m`;
    } else {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.round((seconds % 3600) / 60);
        return `${hours}h ${minutes}m`;
    }
}

/**
 * Show error message
 */
showError(message) {
    // You can integrate this with your existing error handling
    console.error(message);

    // Show a toast or alert
    if (typeof toastr !== 'undefined') {
        toastr.error(message);
    } else {
        alert(message);
    }
}

/**
 * Show success message
 */
showSuccess(message) {
    console.log(message);

    // Show a toast or alert
    if (typeof toastr !== 'undefined') {
        toastr.success(message);
    } else {
        alert(message);
    }
}

/**
 * Hide age banner
 */
hideAgeBanner() {
    $('#analysisAgeBanner').hide();
    $('#libraryChangesAlert').hide();
}

/**
 * Set current analysis ID
 */
setCurrentAnalysisId(analysisId) {
    this.currentAnalysisId = analysisId;
}

/**
 * Get current analysis ID
 */
getCurrentAnalysisId() {
    return this.currentAnalysisId;
}

/**
 * Clear all progress states and hide modals
 */
clearProgressState() {
    console.log('Clearing all progress states and modals');

    // Stop any progress tracking
    if (this.progressUpdateInterval) {
        clearInterval(this.progressUpdateInterval);
        this.progressUpdateInterval = null;
    }

    // Hide all progress-related sections and modals
    $('#progressTrackingSection').hide();
    $('#progressModal').modal('hide');
    $('#confirmDeleteModal').modal('hide');
    $('#loadingSection').hide();

    // Remove any modal backdrops that might be stuck
    $('.modal-backdrop').remove();
    $('body').removeClass('modal-open');

    // Show the main results sections
    $('#duplicateGroupsSection').show();
    $('#statisticsSection').show();
    $('#bulkActionsSection').show();
}

getCSRFToken() {
    // Get CSRF token from meta tag
    return $('meta[name=csrf-token]').attr('content') || '';
}
}

// Initialize the persistence manager when the page loads
$(document).ready(function () {
    window.duplicatePersistenceManager = new DuplicatePersistenceManager();
});