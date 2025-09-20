/**
 * Duplicate Management JavaScript
 * Handles the frontend functionality for the duplicate song management interface
 */

class DuplicateManager {
    constructor() {
        this.duplicateGroups = [];
        this.filteredGroups = [];
        this.selectedDuplicates = new Set();
        this.currentPage = 1;
        this.itemsPerPage = 10;
        this.isLoading = false;
        this.pagination = {};
        this.lastFilterRequest = null; // For cancelling previous requests
        this.virtualScrollEnabled = false;
        this.performanceMode = false;
        this.filterCache = new Map(); // Cache for filter results
        this.currentAnalysisId = null; // Track current analysis for persistence
        
        this.initializeEventListeners();
        this.checkITunesStatus();
        this.initializePerformanceSettings();
        this.checkForExistingAnalysis(); // Check for existing analysis on load
    }
    
    // Debounce function for search input
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
    
    initializeEventListeners() {
        // Main action buttons
        $('#scanDuplicatesBtn').on('click', () => this.scanForDuplicates());
        $('#refreshBtn').on('click', () => this.refreshData());
        $('#rescanBtn').on('click', () => this.scanForDuplicates());
        
        // Enhanced search and filter controls with real-time updates
        $('#searchInput').on('input', this.debounce(() => {
            this.currentPage = 1; // Reset to first page on search
            this.applyFiltersWithCancellation();
        }, 250)); // Reduced debounce time for more responsive search
        
        $('#sortBy').on('change', () => {
            this.currentPage = 1; // Reset to first page on sort change
            this.applyFiltersWithCancellation();
        });
        
        $('#confidenceFilter').on('change', () => {
            this.currentPage = 1; // Reset to first page on filter change
            this.applyFiltersWithCancellation();
        });
        
        $('#clearFiltersBtn').on('click', () => this.clearFilters());
        
        // Bulk action buttons
        $('#selectAllBtn').on('click', () => this.selectAll());
        $('#selectNoneBtn').on('click', () => this.selectNone());
        $('#selectHighConfidenceBtn').on('click', () => this.selectHighConfidence());
        $('#bulkDeleteBtn').on('click', () => this.showBulkDeleteConfirmation());
        $('#smartDeleteBtn').on('click', () => this.showSmartDeleteConfirmation());
        
        // Modal buttons
        $('#confirmDeleteBtn').on('click', () => this.performDeletion());
        
        // Enhanced event delegation for dynamic content
        $(document).on('click', '.toggle-group', (e) => {
            const target = $(e.target).data('target');
            $(target).collapse('toggle');
            const icon = $(e.target).find('i');
            icon.toggleClass('fa-chevron-down fa-chevron-up');
        });
        
        $(document).on('change', '.duplicate-checkbox', (e) => {
            this.handleDuplicateSelection(e);
        });
        
        $(document).on('click', '.individual-delete-btn', (e) => {
            this.handleIndividualDelete(e);
        });
        
        // Keyboard shortcuts for better UX
        $(document).on('keydown', (e) => {
            // Ctrl+F to focus search
            if (e.ctrlKey && e.key === 'f') {
                e.preventDefault();
                $('#searchInput').focus();
            }
            // Escape to clear search
            if (e.key === 'Escape' && $('#searchInput').is(':focus')) {
                this.clearFilters();
            }
        });
    }
    
    async checkITunesStatus() {
        try {
            const response = await fetch('/admin/duplicates/itunes-status');
            const status = await response.json();
            
            const statusDiv = $('#itunesStatus');
            const statusText = $('#itunesStatusText');
            
            if (status.available) {
                statusDiv.removeClass('alert-info alert-warning').addClass('alert-success');
                statusText.html(`<i class="fas fa-check-circle"></i> iTunes integration active (${status.total_tracks} tracks)`);
            } else {
                statusDiv.removeClass('alert-info alert-success').addClass('alert-warning');
                statusText.html(`<i class="fas fa-exclamation-triangle"></i> iTunes integration unavailable - ${status.error || 'Unknown error'}`);
            }
            
            statusDiv.show();
        } catch (error) {
            console.error('Error checking iTunes status:', error);
            $('#itunesStatus').removeClass('alert-info alert-success').addClass('alert-danger');
            $('#itunesStatusText').html('<i class="fas fa-times-circle"></i> Error checking iTunes status');
            $('#itunesStatus').show();
        }
    }
    
    async scanForDuplicates() {
        if (this.isLoading) return;
        
        this.isLoading = true;
        this.showLoading();
        
        try {
            const searchTerm = $('#searchInput').val().trim();
            const sortBy = $('#sortBy').val();
            const minConfidence = parseFloat($('#confidenceFilter').val());
            
            const params = new URLSearchParams();
            if (searchTerm) params.append('search', searchTerm);
            if (sortBy) params.append('sort_by', sortBy);
            if (minConfidence > 0) params.append('min_confidence', minConfidence);
            params.append('page', this.currentPage);
            params.append('per_page', this.itemsPerPage);
            
            const response = await fetch(`/admin/duplicates/analyze?${params}`);
            const data = await response.json();
            
            if (data.success) {
                this.duplicateGroups = data.duplicate_groups || [];
                this.itunesAvailable = data.itunes_available || false;
                this.pagination = data.pagination || {};
                this.updateStatistics(data.analysis || {});
                
                if (this.duplicateGroups.length === 0) {
                    this.showNoResults();
                } else {
                    this.showDuplicateGroups();
                    this.renderDuplicateGroups();
                }
            } else {
                this.showError('Error scanning for duplicates: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            console.error('Error scanning for duplicates:', error);
            this.showError('Network error while scanning for duplicates');
        } finally {
            this.isLoading = false;
            this.hideLoading();
        }
    }
    
    async applyFilters() {
        // Cancel previous request if still pending
        if (this.lastFilterRequest) {
            this.lastFilterRequest.abort();
        }
        
        if (this.isLoading) return;
        
        this.isLoading = true;
        
        // Show loading indicator for search
        this.showFilterLoading();
        
        try {
            const searchTerm = $('#searchInput').val().trim();
            const sortBy = $('#sortBy').val();
            const minConfidence = parseFloat($('#confidenceFilter').val());
            
            const params = new URLSearchParams();
            if (searchTerm) params.append('search', searchTerm);
            if (sortBy) params.append('sort_by', sortBy);
            if (minConfidence > 0) params.append('min_confidence', minConfidence);
            params.append('page', this.currentPage);
            params.append('per_page', this.itemsPerPage);
            
            // Create AbortController for request cancellation
            const controller = new AbortController();
            this.lastFilterRequest = controller;
            
            const response = await fetch(`/admin/duplicates/filter?${params}`, {
                signal: controller.signal
            });
            
            // Clear the request reference if successful
            this.lastFilterRequest = null;
            
            const data = await response.json();
            
            if (data.success) {
                this.filteredGroups = data.duplicate_groups || [];
                this.pagination = data.pagination || {};
                this.renderFilteredGroups();
                
                // Update URL with current filters (for bookmarking/refresh)
                this.updateUrlParams(params);
            } else {
                this.showError('Error filtering duplicates: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                console.log('Filter request was cancelled');
                return; // Don't show error for cancelled requests
            }
            console.error('Error filtering duplicates:', error);
            this.showError('Network error while filtering duplicates');
        } finally {
            this.isLoading = false;
            this.hideFilterLoading();
        }
    }
    
    showFilterLoading() {
        // Show a subtle loading indicator
        $('#duplicateGroupsContainer').prepend(`
            <div id="filterLoadingIndicator" class="text-center py-2">
                <div class="spinner-border spinner-border-sm text-primary" role="status">
                    <span class="sr-only">Filtering...</span>
                </div>
                <small class="ml-2 text-muted">Filtering results...</small>
            </div>
        `);
    }
    
    hideFilterLoading() {
        $('#filterLoadingIndicator').remove();
    }
    
    updateUrlParams(params) {
        // Update browser URL without page reload for better UX
        const url = new URL(window.location);
        url.search = params.toString();
        window.history.replaceState({}, '', url);
    }
    
    renderFilteredGroups() {
        const container = $('#duplicateGroupsContainer');
        container.empty();
        
        if (this.filteredGroups.length === 0) {
            container.html(`
                <div class="card">
                    <div class="card-body text-center py-4">
                        <i class="fas fa-filter text-muted mb-3" style="font-size: 2rem;"></i>
                        <h5>No duplicates match your filters</h5>
                        <p class="text-muted">Try adjusting your search terms or confidence threshold.</p>
                    </div>
                </div>
            `);
            $('#paginationCard').hide();
            return;
        }
        
        // Render groups (they're already paginated from the server)
        this.filteredGroups.forEach((group, index) => {
            const groupHtml = this.renderFilteredDuplicateGroup(group, index);
            container.append(groupHtml);
        });
        
        // Update pagination
        this.updateServerPagination();
    }
    
    renderFilteredDuplicateGroup(group, index) {
        const avgConfidence = group.average_confidence || 0;
        const confidenceClass = avgConfidence >= 0.9 ? 'success' : avgConfidence >= 0.8 ? 'warning' : 'danger';
        const confidenceText = avgConfidence >= 0.9 ? 'Very High' : avgConfidence >= 0.8 ? 'High' : 'Low';
        
        let groupHtml = `
            <div class="card mb-3 duplicate-group" data-group-index="${index}">
                <div class="card-header">
                    <div class="row align-items-center">
                        <div class="col-md-6">
                            <h6 class="mb-0">
                                <i class="fas fa-music text-primary"></i>
                                <strong>${this.escapeHtml(group.canonical_song.song)}</strong>
                                <small class="text-muted">by ${this.escapeHtml(group.canonical_song.artist)}</small>
                            </h6>
                        </div>
                        <div class="col-md-3">
                            <span class="badge badge-${confidenceClass}">${confidenceText} Confidence</span>
                            <span class="badge badge-secondary">${group.duplicates.length} duplicates</span>
                        </div>
                        <div class="col-md-3 text-right">
                            <button class="btn btn-sm btn-outline-primary toggle-group" data-target="#filtered-group-${index}">
                                <i class="fas fa-chevron-down"></i> Show Details
                            </button>
                        </div>
                    </div>
                </div>
                <div class="collapse" id="filtered-group-${index}">
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-6">
                                <h6 class="text-success"><i class="fas fa-star"></i> Canonical Version (Keep)</h6>
                                ${this.renderFilteredTrackDetails(group.canonical_song, false, true)}
                            </div>
                            <div class="col-md-6">
                                <h6 class="text-warning"><i class="fas fa-copy"></i> Duplicate Versions</h6>
                                ${group.duplicates.map(duplicate => this.renderFilteredTrackDetails(duplicate, true, false)).join('')}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        return groupHtml;
    }
    
    renderFilteredTrackDetails(track, isDuplicate = false, isCanonical = false) {
        const playCount = track.play_cnt || 0;
        
        let html = `
            <div class="border rounded p-3 mb-2 ${isCanonical ? 'border-success bg-light' : isDuplicate ? 'border-warning' : ''}" data-track-id="${track.id}">
                <div class="d-flex justify-content-between align-items-start">
                    <div class="flex-grow-1">
                        <div class="d-flex justify-content-between align-items-start mb-2">
                            <div>
                                <strong>${this.escapeHtml(track.song)}</strong>
                                ${isCanonical ? '<span class="badge badge-success ml-2">Recommended</span>' : ''}
                            </div>
                            <div class="text-right">
                                <small class="text-muted">ID: ${track.id}</small>
                            </div>
                        </div>
                        
                        <div class="row">
                            <div class="col-md-6">
                                <small class="text-muted">
                                    <strong>Artist:</strong> ${this.escapeHtml(track.artist)}<br>
                                    <strong>Play Count:</strong> ${playCount}
                                </small>
                            </div>
                        </div>
                    </div>
        `;
        
        if (isDuplicate) {
            const isSelected = this.selectedDuplicates.has(track.id);
            html += `
                    <div class="ml-3">
                        <div class="form-check">
                            <input class="form-check-input duplicate-checkbox" type="checkbox" 
                                   id="duplicate-${track.id}" data-track-id="${track.id}" ${isSelected ? 'checked' : ''}>
                            <label class="form-check-label" for="duplicate-${track.id}">
                                <strong>Delete</strong>
                            </label>
                        </div>
                        
                        <div class="mt-2">
                            <button class="btn btn-sm btn-outline-danger individual-delete-btn" 
                                    data-track-id="${track.id}" 
                                    data-song="${this.escapeHtml(track.song)}" 
                                    data-artist="${this.escapeHtml(track.artist)}"
                                    title="Delete this duplicate immediately">
                                <i class="fas fa-trash"></i> Delete Now
                            </button>
                        </div>
                    </div>
            `;
        }
        
        html += `
                </div>
            </div>
        `;
        
        return html;
    }
    
    updateServerPagination() {
        const paginationList = $('#paginationList');
        const paginationCard = $('#paginationCard');
        
        if (!this.pagination || this.pagination.total_pages <= 1) {
            paginationCard.hide();
            return;
        }
        
        paginationCard.show();
        paginationList.empty();
        
        const currentPage = this.pagination.current_page;
        const totalPages = this.pagination.total_pages;
        
        // Previous button
        const prevDisabled = !this.pagination.has_prev ? 'disabled' : '';
        paginationList.append(`
            <li class="page-item ${prevDisabled}">
                <a class="page-link" href="#" data-page="${currentPage - 1}">Previous</a>
            </li>
        `);
        
        // Page numbers
        const startPage = Math.max(1, currentPage - 2);
        const endPage = Math.min(totalPages, currentPage + 2);
        
        if (startPage > 1) {
            paginationList.append(`<li class="page-item"><a class="page-link" href="#" data-page="1">1</a></li>`);
            if (startPage > 2) {
                paginationList.append(`<li class="page-item disabled"><span class="page-link">...</span></li>`);
            }
        }
        
        for (let i = startPage; i <= endPage; i++) {
            const activeClass = i === currentPage ? 'active' : '';
            paginationList.append(`
                <li class="page-item ${activeClass}">
                    <a class="page-link" href="#" data-page="${i}">${i}</a>
                </li>
            `);
        }
        
        if (endPage < totalPages) {
            if (endPage < totalPages - 1) {
                paginationList.append(`<li class="page-item disabled"><span class="page-link">...</span></li>`);
            }
            paginationList.append(`<li class="page-item"><a class="page-link" href="#" data-page="${totalPages}">${totalPages}</a></li>`);
        }
        
        // Next button
        const nextDisabled = !this.pagination.has_next ? 'disabled' : '';
        paginationList.append(`
            <li class="page-item ${nextDisabled}">
                <a class="page-link" href="#" data-page="${currentPage + 1}">Next</a>
            </li>
        `);
        
        // Add click handlers for pagination
        $('#paginationList a.page-link').on('click', (e) => {
            e.preventDefault();
            const page = parseInt($(e.target).data('page'));
            if (page && page !== currentPage) {
                this.currentPage = page;
                this.applyFilters();
            }
        });
    }
    
    sortGroups(sortBy) {
        this.filteredGroups.sort((a, b) => {
            switch (sortBy) {
                case 'artist':
                    return a.canonical_song.artist.localeCompare(b.canonical_song.artist);
                case 'song':
                    return a.canonical_song.song.localeCompare(b.canonical_song.song);
                case 'duplicates':
                    return b.duplicates.length - a.duplicates.length;
                case 'confidence':
                    return this.getAverageConfidence(b) - this.getAverageConfidence(a);
                default:
                    return 0;
            }
        });
    }
    
    getAverageConfidence(group) {
        const scores = Object.values(group.similarity_scores);
        return scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
    }
    
    clearFilters() {
        $('#searchInput').val('');
        $('#sortBy').val('artist');
        $('#confidenceFilter').val('0.8');
        this.applyFilters();
    }
    
    updateStatistics(analysis) {
        $('#totalGroupsCount').text(analysis.total_groups || 0);
        $('#totalDuplicatesCount').text(analysis.total_duplicates || 0);
        $('#potentialDeletionsCount').text(analysis.potential_deletions || 0);
        $('#spaceSavings').text(analysis.estimated_space_savings || '0 MB');
        $('#highConfidenceCount').text(analysis.groups_with_high_confidence || 0);
        $('#avgSimilarity').text(Math.round((analysis.average_similarity_score || 0) * 100) + '%');
        
        // Add iTunes integration statistics if available
        if (this.itunesAvailable) {
            const itunesMatches = this.countITunesMatches();
            const itunesStatsHtml = `
                <div class="col-md-2">
                    <div class="text-center">
                        <h4 class="text-info mb-1">${itunesMatches.total}</h4>
                        <small class="text-muted">iTunes Matches</small>
                    </div>
                </div>
                <div class="col-md-2">
                    <div class="text-center">
                        <h4 class="text-success mb-1">${itunesMatches.exact}</h4>
                        <small class="text-muted">Exact Matches</small>
                    </div>
                </div>
            `;
            
            // Insert iTunes stats before the last column
            $('#statisticsSection .row').append(itunesStatsHtml);
        }
        
        $('#statisticsSection').show();
        $('#bulkActionsSection').show();
    }
    
    countITunesMatches() {
        let total = 0;
        let exact = 0;
        
        this.duplicateGroups.forEach(group => {
            if (group.itunes_matches) {
                Object.values(group.itunes_matches).forEach(match => {
                    if (match.found) {
                        total++;
                        if (match.match_type === 'exact') {
                            exact++;
                        }
                    }
                });
            }
        });
        
        return { total, exact };
    }
    
    renderDuplicateGroups() {
        const container = $('#duplicateGroupsContainer');
        container.empty();
        
        if (this.filteredGroups.length === 0) {
            container.html(`
                <div class="card">
                    <div class="card-body text-center py-4">
                        <i class="fas fa-filter text-muted mb-3" style="font-size: 2rem;"></i>
                        <h5>No duplicates match your filters</h5>
                        <p class="text-muted">Try adjusting your search terms or confidence threshold.</p>
                    </div>
                </div>
            `);
            return;
        }
        
        // Calculate pagination
        const startIndex = (this.currentPage - 1) * this.itemsPerPage;
        const endIndex = startIndex + this.itemsPerPage;
        const pageGroups = this.filteredGroups.slice(startIndex, endIndex);
        
        // Render groups
        pageGroups.forEach((group, index) => {
            const groupHtml = this.renderDuplicateGroup(group, startIndex + index);
            container.append(groupHtml);
        });
        
        // Update pagination
        this.updatePagination();
    }
    
    updatePagination() {
        const totalPages = Math.ceil(this.filteredGroups.length / this.itemsPerPage);
        const paginationList = $('#paginationList');
        const paginationCard = $('#paginationCard');
        
        if (totalPages <= 1) {
            paginationCard.hide();
            return;
        }
        
        paginationCard.show();
        paginationList.empty();
        
        // Previous button
        const prevDisabled = this.currentPage === 1 ? 'disabled' : '';
        paginationList.append(`
            <li class="page-item ${prevDisabled}">
                <a class="page-link" href="#" data-page="${this.currentPage - 1}">Previous</a>
            </li>
        `);
        
        // Page numbers
        const startPage = Math.max(1, this.currentPage - 2);
        const endPage = Math.min(totalPages, this.currentPage + 2);
        
        if (startPage > 1) {
            paginationList.append(`<li class="page-item"><a class="page-link" href="#" data-page="1">1</a></li>`);
            if (startPage > 2) {
                paginationList.append(`<li class="page-item disabled"><span class="page-link">...</span></li>`);
            }
        }
        
        for (let i = startPage; i <= endPage; i++) {
            const activeClass = i === this.currentPage ? 'active' : '';
            paginationList.append(`
                <li class="page-item ${activeClass}">
                    <a class="page-link" href="#" data-page="${i}">${i}</a>
                </li>
            `);
        }
        
        if (endPage < totalPages) {
            if (endPage < totalPages - 1) {
                paginationList.append(`<li class="page-item disabled"><span class="page-link">...</span></li>`);
            }
            paginationList.append(`<li class="page-item"><a class="page-link" href="#" data-page="${totalPages}">${totalPages}</a></li>`);
        }
        
        // Next button
        const nextDisabled = this.currentPage === totalPages ? 'disabled' : '';
        paginationList.append(`
            <li class="page-item ${nextDisabled}">
                <a class="page-link" href="#" data-page="${this.currentPage + 1}">Next</a>
            </li>
        `);
    }
    
    renderDuplicateGroup(group, index) {
        const avgConfidence = this.getAverageConfidence(group);
        const confidenceClass = avgConfidence >= 0.9 ? 'success' : avgConfidence >= 0.8 ? 'warning' : 'danger';
        const confidenceText = avgConfidence >= 0.9 ? 'Very High' : avgConfidence >= 0.8 ? 'High' : 'Low';
        
        let groupHtml = `
            <div class="card mb-3 duplicate-group" data-group-index="${index}">
                <div class="card-header">
                    <div class="row align-items-center">
                        <div class="col-md-6">
                            <h6 class="mb-0">
                                <i class="fas fa-music text-primary"></i>
                                <strong>${this.escapeHtml(group.canonical_song.song)}</strong>
                                <small class="text-muted">by ${this.escapeHtml(group.canonical_song.artist)}</small>
                            </h6>
                        </div>
                        <div class="col-md-3">
                            <span class="badge badge-${confidenceClass}">${confidenceText} Confidence</span>
                            <span class="badge badge-secondary">${group.duplicates.length} duplicates</span>
                        </div>
                        <div class="col-md-3 text-right">
                            <button class="btn btn-sm btn-outline-primary toggle-group" data-target="#group-${index}">
                                <i class="fas fa-chevron-down"></i> Show Details
                            </button>
                        </div>
                    </div>
                </div>
                <div class="collapse" id="group-${index}">
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-6">
                                <h6 class="text-success"><i class="fas fa-star"></i> Canonical Version (Keep)</h6>
                                ${this.renderTrackDetails(
                                    group.canonical_song, 
                                    false, 
                                    true, 
                                    group.itunes_matches ? group.itunes_matches[group.canonical_song.id] : null
                                )}
                            </div>
                            <div class="col-md-6">
                                <h6 class="text-warning"><i class="fas fa-copy"></i> Duplicate Versions</h6>
                                ${group.duplicates.map(duplicate => this.renderTrackDetails(
                                    duplicate, 
                                    true, 
                                    false, 
                                    group.itunes_matches ? group.itunes_matches[duplicate.id] : null
                                )).join('')}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        return groupHtml;
    }
    
    renderTrackDetails(track, isDuplicate = false, isCanonical = false, itunesMatch = null) {
        const playCount = track.play_cnt || 0;
        const lastPlayed = track.last_play_dt ? new Date(track.last_play_dt).toLocaleDateString() : 'Never';
        const dateAdded = track.date_added ? new Date(track.date_added).toLocaleDateString() : 'Unknown';
        
        // iTunes integration indicators
        let itunesIndicator = '';
        if (itunesMatch) {
            if (itunesMatch.found) {
                const matchTypeClass = itunesMatch.match_type === 'exact' ? 'success' : 'warning';
                const matchTypeText = itunesMatch.match_type === 'exact' ? 'Exact Match' : 'Fuzzy Match';
                const confidencePercent = Math.round(itunesMatch.confidence_score * 100);
                
                itunesIndicator = `
                    <div class="mb-2">
                        <span class="badge badge-${matchTypeClass}" title="iTunes ${matchTypeText} (${confidencePercent}% confidence)">
                            <i class="fab fa-apple"></i> iTunes ${matchTypeText}
                        </span>
                        ${itunesMatch.metadata_differences.length > 0 ? 
                            `<button class="btn btn-sm btn-outline-info ml-1" onclick="showMetadataDifferences(${track.id})" title="Show metadata differences">
                                <i class="fas fa-info-circle"></i>
                            </button>` : ''
                        }
                    </div>
                `;
            } else {
                itunesIndicator = `
                    <div class="mb-2">
                        <span class="badge badge-secondary" title="Not found in iTunes library">
                            <i class="fab fa-apple"></i> Not in iTunes
                        </span>
                    </div>
                `;
            }
        }
        
        let html = `
            <div class="border rounded p-3 mb-2 ${isCanonical ? 'border-success bg-light' : isDuplicate ? 'border-warning' : ''}" data-track-id="${track.id}">
                <div class="d-flex justify-content-between align-items-start">
                    <div class="flex-grow-1">
                        <div class="d-flex justify-content-between align-items-start mb-2">
                            <div>
                                <strong>${this.escapeHtml(track.song)}</strong>
                                ${isCanonical ? '<span class="badge badge-success ml-2">Recommended</span>' : ''}
                            </div>
                            <div class="text-right">
                                <small class="text-muted">ID: ${track.id}</small>
                            </div>
                        </div>
                        
                        ${itunesIndicator}
                        
                        <div class="row">
                            <div class="col-md-6">
                                <small class="text-muted">
                                    <strong>Artist:</strong> ${this.escapeHtml(track.artist)}<br>
                                    <strong>Album:</strong> ${this.escapeHtml(track.album || 'Unknown')}<br>
                                </small>
                            </div>
                            <div class="col-md-6">
                                <small class="text-muted">
                                    <strong>Play Count:</strong> ${playCount}<br>
                                    <strong>Last Played:</strong> ${lastPlayed}<br>
                                    <strong>Date Added:</strong> ${dateAdded}
                                </small>
                            </div>
                        </div>
                        
                        <!-- Expandable details section -->
                        <div class="mt-2">
                            <button class="btn btn-sm btn-outline-secondary" type="button" data-toggle="collapse" 
                                    data-target="#details-${track.id}" aria-expanded="false">
                                <i class="fas fa-chevron-down"></i> More Details
                            </button>
                        </div>
                        
                        <div class="collapse mt-2" id="details-${track.id}">
                            <div class="card card-body bg-light">
                                <div class="row">
                                    <div class="col-md-6">
                                        <h6>Database Information</h6>
                                        <small>
                                            <strong>Track ID:</strong> ${track.id}<br>
                                            <strong>Category:</strong> ${track.category || 'Not set'}<br>
                                            <strong>Location:</strong> ${track.location || 'Not available'}<br>
                                        </small>
                                    </div>
                                    <div class="col-md-6">
                                        ${itunesMatch && itunesMatch.found ? `
                                            <h6>iTunes Information</h6>
                                            <small>
                                                <strong>iTunes Name:</strong> ${this.escapeHtml(itunesMatch.itunes_track.name)}<br>
                                                <strong>iTunes Artist:</strong> ${this.escapeHtml(itunesMatch.itunes_track.artist)}<br>
                                                <strong>iTunes Album:</strong> ${this.escapeHtml(itunesMatch.itunes_track.album || 'Unknown')}<br>
                                                <strong>iTunes Plays:</strong> ${itunesMatch.itunes_track.play_count || 0}<br>
                                                <strong>Genre:</strong> ${this.escapeHtml(itunesMatch.itunes_track.genre || 'Unknown')}
                                            </small>
                                        ` : '<h6>iTunes Information</h6><small class="text-muted">Not available in iTunes</small>'}
                                    </div>
                                </div>
                                
                                ${itunesMatch && itunesMatch.metadata_differences.length > 0 ? `
                                    <div class="mt-3">
                                        <h6>Metadata Differences</h6>
                                        <ul class="list-unstyled">
                                            ${itunesMatch.metadata_differences.map(diff => `
                                                <li><small class="text-warning"><i class="fas fa-exclamation-triangle"></i> ${this.escapeHtml(diff)}</small></li>
                                            `).join('')}
                                        </ul>
                                    </div>
                                ` : ''}
                            </div>
                        </div>
                    </div>
        `;
        
        if (isDuplicate) {
            const isSelected = this.selectedDuplicates.has(track.id);
            html += `
                    <div class="ml-3">
                        <div class="form-check">
                            <input class="form-check-input duplicate-checkbox" type="checkbox" 
                                   id="duplicate-${track.id}" data-track-id="${track.id}" ${isSelected ? 'checked' : ''}>
                            <label class="form-check-label" for="duplicate-${track.id}">
                                <strong>Delete</strong>
                            </label>
                        </div>
                        
                        <!-- Individual delete button -->
                        <div class="mt-2">
                            <button class="btn btn-sm btn-outline-danger individual-delete-btn" 
                                    data-track-id="${track.id}" 
                                    data-song="${this.escapeHtml(track.song)}" 
                                    data-artist="${this.escapeHtml(track.artist)}"
                                    title="Delete this duplicate immediately">
                                <i class="fas fa-trash"></i> Delete Now
                            </button>
                        </div>
                        
                        <!-- Risk indicators -->
                        <div class="mt-2">
                            ${playCount > 0 ? `<span class="badge badge-info" title="This track has been played ${playCount} times">
                                <i class="fas fa-play"></i> ${playCount} plays
                            </span>` : ''}
                            
                            ${itunesMatch && itunesMatch.found ? `<span class="badge badge-success" title="Found in iTunes library">
                                <i class="fab fa-apple"></i> In iTunes
                            </span>` : `<span class="badge badge-warning" title="Not found in iTunes library">
                                <i class="fas fa-exclamation-triangle"></i> Not in iTunes
                            </span>`}
                        </div>
                    </div>
            `;
        }
        
        html += `
                </div>
            </div>
        `;
        
        return html;
    }
    
    showError(message) {
        // Show error in a toast or alert
        const alertHtml = `
            <div class="alert alert-danger alert-dismissible fade show" role="alert">
                <i class="fas fa-exclamation-circle"></i> ${message}
                <button type="button" class="close" data-dismiss="alert">
                    <span>&times;</span>
                </button>
            </div>
        `;
        $('.container-fluid').prepend(alertHtml);
    }
    
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    showLoading() {
        $('#loadingSection').show();
        $('#noResultsSection').hide();
        $('#duplicateGroupsSection').hide();
        $('#statisticsSection').hide();
        $('#bulkActionsSection').hide();
    }
    
    hideLoading() {
        $('#loadingSection').hide();
    }
    
    showNoResults() {
        $('#noResultsSection').show();
        $('#duplicateGroupsSection').hide();
        $('#statisticsSection').hide();
        $('#bulkActionsSection').hide();
    }
    
    showDuplicateGroups() {
        $('#duplicateGroupsSection').show();
        $('#noResultsSection').hide();
    }
    
    // Selection methods
    selectAll() {
        $('.duplicate-checkbox:visible').prop('checked', true).trigger('change');
    }
    
    selectNone() {
        $('.duplicate-checkbox').prop('checked', false).trigger('change');
    }
    
    selectHighConfidence() {
        this.selectNone();
        // Select duplicates from high confidence groups
        this.filteredGroups.forEach(group => {
            if (this.getAverageConfidence(group) >= 0.9) {
                group.duplicates.forEach(duplicate => {
                    $(`#duplicate-${duplicate.id}`).prop('checked', true).trigger('change');
                });
            }
        });
    }
    
    refreshData() {
        this.selectedDuplicates.clear();
        this.updateSelectedCount();
        this.scanForDuplicates();
    }
    
    updateSelectedCount() {
        const count = this.selectedDuplicates.size;
        $('#selectedCount').text(`${count} selected`);
        $('#bulkDeleteBtn').prop('disabled', count === 0);
        $('#smartDeleteBtn').prop('disabled', this.filteredGroups.length === 0);
        
        // Update button text based on selection
        if (count > 0) {
            $('#bulkDeleteBtn').html(`<i class="fas fa-trash"></i> Delete ${count} Selected`);
        } else {
            $('#bulkDeleteBtn').html(`<i class="fas fa-trash"></i> Delete Selected`);
        }
    }
    
    showBulkDeleteConfirmation() {
        if (this.selectedDuplicates.size === 0) return;
        
        // Prepare delete preview
        const selectedTracks = [];
        this.duplicateGroups.forEach(group => {
            group.duplicates.forEach(duplicate => {
                if (this.selectedDuplicates.has(duplicate.id)) {
                    selectedTracks.push({
                        ...duplicate,
                        itunesMatch: group.itunes_matches ? group.itunes_matches[duplicate.id] : null
                    });
                }
            });
        });
        
        let previewHtml = `
            <h6>You are about to delete ${selectedTracks.length} duplicate songs:</h6>
            <div class="list-group" style="max-height: 300px; overflow-y: auto;">
        `;
        
        selectedTracks.forEach(track => {
            const itunesIndicator = track.itunesMatch && track.itunesMatch.found ? 
                '<span class="badge badge-success"><i class="fab fa-apple"></i> In iTunes</span>' :
                '<span class="badge badge-warning"><i class="fas fa-exclamation-triangle"></i> Not in iTunes</span>';
            
            previewHtml += `
                <div class="list-group-item">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <strong>${this.escapeHtml(track.song)}</strong><br>
                            <small class="text-muted">by ${this.escapeHtml(track.artist)} | ${track.play_cnt || 0} plays</small>
                        </div>
                        <div>
                            ${itunesIndicator}
                        </div>
                    </div>
                </div>
            `;
        });
        
        previewHtml += '</div>';
        
        $('#deletePreview').html(previewHtml);
        $('#confirmDeleteModal').modal('show');
    }
    
    async performDeletion() {
        if (this.selectedDuplicates.size === 0) return;
        
        // Hide confirmation modal and wait for it to fully close
        $('#confirmDeleteModal').modal('hide');
        
        // Wait a moment for the modal to fully close before showing progress
        await new Promise(resolve => setTimeout(resolve, 300));
        
        $('#progressModal').modal('show');
        $('#progressText').text('Deleting selected duplicates...');
        
        try {
            const trackIds = Array.from(this.selectedDuplicates);
            
            const response = await fetch('/admin/duplicates/bulk-delete', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    track_ids: trackIds
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showSuccess(`Successfully deleted ${result.deleted_count} duplicate songs.`);
                
                // Clear selections and update display
                this.selectedDuplicates.clear();
                this.updateSelectedCount();
                
                // Clear all progress states and modals
                this.clearProgressState();
                
                // After delete, refresh the persistent analysis to show updated results
                if (this.currentAnalysisId && window.duplicatePersistenceManager) {
                    console.log('Refreshing analysis after delete operation');
                    try {
                        await window.duplicatePersistenceManager.loadAnalysis(this.currentAnalysisId);
                        console.log('Analysis refresh completed after delete');
                    } catch (error) {
                        console.error('Error refreshing analysis after delete:', error);
                        // Fallback to local update
                        this.removeDeletedTracksFromResults(trackIds);
                        this.renderDuplicateGroups();
                    }
                } else {
                    // Fallback: Remove deleted tracks from current results
                    this.removeDeletedTracksFromResults(trackIds);
                    this.renderDuplicateGroups();
                }
            } else {
                $('#progressModal').modal('hide');
                this.showError('Error deleting duplicates: ' + (result.error || 'Unknown error'));
            }
        } catch (error) {
            $('#progressModal').modal('hide');
            console.error('Error deleting duplicates:', error);
            this.showError('Network error while deleting duplicates');
        }
    }
    
    async deleteIndividualTrack(trackId, songName, artistName) {
        // Show confirmation dialog
        const confirmed = confirm(
            `Are you sure you want to delete "${songName}" by ${artistName}?\n\n` +
            'This action cannot be undone.'
        );
        
        if (!confirmed) return;
        
        try {
            const response = await fetch('/admin/duplicates/delete', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    track_id: trackId
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showSuccess(result.message);
                
                // Remove from selected duplicates if it was selected
                this.selectedDuplicates.delete(trackId);
                this.updateSelectedCount();
                
                // Clear all progress states and modals
                this.clearProgressState();
                
                // After delete, refresh the persistent analysis to show updated results
                if (this.currentAnalysisId && window.duplicatePersistenceManager) {
                    console.log('Refreshing analysis after individual delete operation');
                    try {
                        await window.duplicatePersistenceManager.loadAnalysis(this.currentAnalysisId);
                        console.log('Analysis refresh completed after individual delete');
                    } catch (error) {
                        console.error('Error refreshing analysis after individual delete:', error);
                        // Fallback to local update
                        this.removeDeletedTracksFromResults([trackId]);
                        this.renderDuplicateGroups();
                    }
                } else {
                    // Fallback: Remove deleted track from current results
                    this.removeDeletedTracksFromResults([trackId]);
                    this.renderDuplicateGroups();
                }
            } else {
                this.showError('Error deleting track: ' + (result.error || 'Unknown error'));
            }
        } catch (error) {
            console.error('Error deleting individual track:', error);
            this.showError('Network error while deleting track');
        }
    }
    
    showSmartDeleteConfirmation() {
        if (this.filteredGroups.length === 0) return;
        
        const strategy = $('#smartDeletionStrategy').val();
        const strategyNames = {
            'keep_most_played': 'Keep Most Played',
            'keep_itunes_version': 'Keep iTunes Version',
            'keep_shortest_title': 'Keep Shortest Title',
            'keep_canonical': 'Keep Canonical'
        };
        
        // Prepare smart delete preview
        let previewHtml = `
            <h6>Smart Deletion Strategy: ${strategyNames[strategy]}</h6>
            <p>This will automatically select which duplicates to delete from each group based on the chosen strategy.</p>
            <div class="alert alert-info">
                <strong>Strategy Details:</strong><br>
                ${this.getStrategyDescription(strategy)}
            </div>
            <p><strong>Groups to process:</strong> ${this.filteredGroups.length}</p>
        `;
        
        $('#deletePreview').html(previewHtml);
        $('#confirmDeleteModalLabel').html('<i class="fas fa-magic text-success"></i> Confirm Smart Deletion');
        $('#confirmDeleteBtn').html('<i class="fas fa-magic"></i> Apply Smart Deletion');
        $('#confirmDeleteBtn').removeClass('btn-danger').addClass('btn-success');
        $('#confirmDeleteBtn').off('click').on('click', () => this.performSmartDeletion());
        $('#confirmDeleteModal').modal('show');
    }
    
    getStrategyDescription(strategy) {
        const descriptions = {
            'keep_most_played': 'Keeps the version with the highest play count in each duplicate group.',
            'keep_itunes_version': 'Keeps the version that exactly matches your iTunes library. Falls back to most played if no iTunes match.',
            'keep_shortest_title': 'Keeps the version with the shortest title (likely the original version without suffixes).',
            'keep_canonical': 'Uses intelligent analysis to determine the best version to keep based on multiple factors.'
        };
        return descriptions[strategy] || 'Unknown strategy';
    }
    
    async performSmartDeletion() {
        $('#confirmDeleteModal').modal('hide');
        $('#progressModal').modal('show');
        $('#progressText').text('Applying smart deletion strategy...');
        
        try {
            const strategy = $('#smartDeletionStrategy').val();
            
            // Prepare duplicate groups data
            const duplicateGroupsData = this.filteredGroups.map((group, index) => ({
                group_id: index,
                track_ids: [group.canonical_song.id, ...group.duplicates.map(d => d.id)]
            }));
            
            const response = await fetch('/admin/duplicates/smart-delete', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    duplicate_groups: duplicateGroupsData,
                    strategy: strategy
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                $('#progressModal').modal('hide');
                
                const summary = result.deletion_summary;
                this.showSuccess(
                    `Smart deletion completed! Processed ${summary.groups_processed} groups, ` +
                    `deleted ${summary.tracks_to_delete} tracks, kept ${summary.tracks_to_keep} tracks.`
                );
                
                // Clear selections and refresh
                this.selectedDuplicates.clear();
                this.updateSelectedCount();
                this.refreshData();
            } else {
                $('#progressModal').modal('hide');
                this.showError('Error in smart deletion: ' + (result.error || 'Unknown error'));
            }
        } catch (error) {
            $('#progressModal').modal('hide');
            console.error('Error in smart deletion:', error);
            this.showError('Network error during smart deletion');
        } finally {
            // Reset modal for regular deletion
            $('#confirmDeleteModalLabel').html('<i class="fas fa-exclamation-triangle text-warning"></i> Confirm Deletion');
            $('#confirmDeleteBtn').html('<i class="fas fa-trash"></i> Delete Songs');
            $('#confirmDeleteBtn').removeClass('btn-success').addClass('btn-danger');
            $('#confirmDeleteBtn').off('click').on('click', () => this.performDeletion());
        }
    }
    
    showSuccess(message) {
        const alertHtml = `
            <div class="alert alert-success alert-dismissible fade show" role="alert">
                <i class="fas fa-check-circle"></i> ${message}
                <button type="button" class="close" data-dismiss="alert">
                    <span>&times;</span>
                </button>
            </div>
        `;
        $('.container-fluid').prepend(alertHtml);
        
        // Auto-dismiss after 5 seconds
        setTimeout(() => {
            $('.alert-success').alert('close');
        }, 5000);
    }
    
    /**
     * Clear all progress states and hide modals
     */
    clearProgressState() {
        console.log('Clearing all progress states and modals in duplicate manager');
        
        // Hide all modals that might be open
        $('#progressModal').modal('hide');
        $('#confirmDeleteModal').modal('hide');
        $('#progressTrackingSection').hide();
        $('#loadingSection').hide();
        
        // Remove any modal backdrops that might be stuck
        $('.modal-backdrop').remove();
        $('body').removeClass('modal-open');
        
        // Ensure main sections are visible
        $('#duplicateGroupsSection').show();
        $('#statisticsSection').show();
        $('#bulkActionsSection').show();
    }
    
    getCSRFToken() {
        // Get CSRF token from meta tag
        return $('meta[name=csrf-token]').attr('content') || '';
    }
    
    // Enhanced event handlers for better UX
    handleDuplicateSelection(e) {
        const trackId = parseInt($(e.target).data('track-id'));
        const isChecked = $(e.target).is(':checked');
        
        if (isChecked) {
            this.selectedDuplicates.add(trackId);
        } else {
            this.selectedDuplicates.delete(trackId);
        }
        
        this.updateSelectionUI();
    }
    
    handleIndividualDelete(e) {
        e.preventDefault();
        const trackId = $(e.target).data('track-id');
        const songName = $(e.target).data('song');
        const artistName = $(e.target).data('artist');
        
        this.showIndividualDeleteConfirmation(trackId, songName, artistName);
    }
    
    updateSelectionUI() {
        const selectedCount = this.selectedDuplicates.size;
        $('#selectedCount').text(`${selectedCount} selected`);
        
        // Enable/disable bulk action buttons
        const hasSelection = selectedCount > 0;
        $('#bulkDeleteBtn').prop('disabled', !hasSelection);
        $('#smartDeleteBtn').prop('disabled', !hasSelection);
        
        // Update select all button text
        const totalCheckboxes = $('.duplicate-checkbox').length;
        const allSelected = selectedCount === totalCheckboxes && totalCheckboxes > 0;
        $('#selectAllBtn').html(allSelected ? 
            '<i class="fas fa-check-square"></i> All Selected' : 
            '<i class="fas fa-check-square"></i> Select All'
        );
    }
    
    showIndividualDeleteConfirmation(trackId, songName, artistName) {
        const modalHtml = `
            <div class="modal fade" id="individualDeleteModal" tabindex="-1" role="dialog">
                <div class="modal-dialog" role="document">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">
                                <i class="fas fa-exclamation-triangle text-warning"></i> Confirm Individual Deletion
                            </h5>
                            <button type="button" class="close" data-dismiss="modal">
                                <span>&times;</span>
                            </button>
                        </div>
                        <div class="modal-body">
                            <div class="alert alert-warning">
                                <strong>Warning:</strong> This action cannot be undone.
                            </div>
                            <p>Are you sure you want to delete this song?</p>
                            <div class="card">
                                <div class="card-body">
                                    <h6><strong>${this.escapeHtml(songName)}</strong></h6>
                                    <p class="text-muted mb-0">by ${this.escapeHtml(artistName)}</p>
                                </div>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-dismiss="modal">Cancel</button>
                            <button type="button" class="btn btn-danger" id="confirmIndividualDeleteBtn" data-track-id="${trackId}">
                                <i class="fas fa-trash"></i> Delete Song
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Remove existing modal if present
        $('#individualDeleteModal').remove();
        
        // Add new modal to body
        $('body').append(modalHtml);
        
        // Show modal
        $('#individualDeleteModal').modal('show');
        
        // Handle confirm button
        $('#confirmIndividualDeleteBtn').on('click', async (e) => {
            const trackId = $(e.target).data('track-id');
            await this.performIndividualDeletion(trackId);
            $('#individualDeleteModal').modal('hide');
        });
        
        // Clean up modal after hiding
        $('#individualDeleteModal').on('hidden.bs.modal', () => {
            $('#individualDeleteModal').remove();
        });
    }
    
    async performIndividualDeletion(trackId) {
        try {
            this.showProgressModal('Deleting song...', 'Please wait while the song is being deleted.');
            
            const response = await fetch('/admin/duplicates/delete', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ track_id: trackId })
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showSuccess(result.message);
                
                // Remove the track from UI
                $(`.duplicate-checkbox[data-track-id="${trackId}"]`).closest('.border').fadeOut(() => {
                    $(`.duplicate-checkbox[data-track-id="${trackId}"]`).closest('.border').remove();
                });
                
                // Update selection
                this.selectedDuplicates.delete(trackId);
                this.updateSelectionUI();
                
                // Refresh data to get updated statistics
                setTimeout(() => this.refreshData(), 1000);
            } else {
                this.showError('Failed to delete song: ' + result.error);
            }
        } catch (error) {
            console.error('Error deleting individual song:', error);
            this.showError('Network error while deleting song');
        } finally {
            this.hideProgressModal();
        }
    }
    
    showProgressModal(title, message) {
        $('#progressModalLabel').text(title);
        $('#progressText').text(message);
        $('#progressBar').css('width', '50%');
        $('#progressModal').modal('show');
    }
    
    hideProgressModal() {
        $('#progressModal').modal('hide');
    }
    
    // Enhanced filtering with better performance
    async applyFiltersWithPerformanceOptimization() {
        // Cancel previous request if still pending
        if (this.lastFilterRequest) {
            this.lastFilterRequest.abort();
        }
        
        if (this.isLoading) return;
        
        this.isLoading = true;
        
        // Show loading indicator for search
        this.showFilterLoading();
        
        try {
            const searchTerm = $('#searchInput').val().trim();
            const sortBy = $('#sortBy').val();
            const minConfidence = parseFloat($('#confidenceFilter').val());
            
            const params = new URLSearchParams();
            if (searchTerm) params.append('search', searchTerm);
            if (sortBy) params.append('sort_by', sortBy);
            if (minConfidence > 0) params.append('min_confidence', minConfidence);
            params.append('page', this.currentPage);
            params.append('per_page', this.itemsPerPage);
            
            // Add performance optimization flag
            params.append('optimize', 'true');
            
            // Create AbortController for request cancellation
            const controller = new AbortController();
            this.lastFilterRequest = controller;
            
            const response = await fetch(`/admin/duplicates/filter?${params}`, {
                signal: controller.signal,
                headers: {
                    'Cache-Control': 'no-cache',
                    'Pragma': 'no-cache'
                }
            });
            
            // Clear the request reference if successful
            this.lastFilterRequest = null;
            
            const data = await response.json();
            
            if (data.success) {
                this.filteredGroups = data.duplicate_groups || [];
                this.pagination = data.pagination || {};
                this.renderFilteredGroups();
                
                // Update URL with current filters (for bookmarking/refresh)
                this.updateUrlParams(params);
                
                // Update performance metrics if available
                if (data.performance_metrics) {
                    this.updatePerformanceMetrics(data.performance_metrics);
                }
            } else {
                this.showError('Error filtering duplicates: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                console.log('Filter request was cancelled');
                return; // Don't show error for cancelled requests
            }
            console.error('Error filtering duplicates:', error);
            this.showError('Network error while filtering duplicates');
        } finally {
            this.isLoading = false;
            this.hideFilterLoading();
        }
    }
    
    updatePerformanceMetrics(metrics) {
        // Display performance information for debugging/optimization
        if (window.console && console.log) {
            console.log('Filter Performance:', {
                'Query Time': metrics.query_time + 'ms',
                'Processing Time': metrics.processing_time + 'ms',
                'Total Results': metrics.total_results,
                'Filtered Results': metrics.filtered_results
            });
        }
    }
    
    // Virtual scrolling implementation for large datasets
    initializeVirtualScrolling() {
        const container = $('#duplicateGroupsContainer');
        let isScrolling = false;
        
        $(window).on('scroll', this.debounce(() => {
            if (isScrolling) return;
            
            const scrollTop = $(window).scrollTop();
            const windowHeight = $(window).height();
            const documentHeight = $(document).height();
            
            // Load more when user scrolls to 80% of the page
            if (scrollTop + windowHeight >= documentHeight * 0.8) {
                this.loadMoreResults();
            }
        }, 100));
    }
    
    async loadMoreResults() {
        if (!this.pagination || !this.pagination.has_next || this.isLoading) {
            return;
        }
        
        this.isLoading = true;
        
        try {
            const nextPage = this.pagination.current_page + 1;
            const searchTerm = $('#searchInput').val().trim();
            const sortBy = $('#sortBy').val();
            const minConfidence = parseFloat($('#confidenceFilter').val());
            
            const params = new URLSearchParams();
            if (searchTerm) params.append('search', searchTerm);
            if (sortBy) params.append('sort_by', sortBy);
            if (minConfidence > 0) params.append('min_confidence', minConfidence);
            params.append('page', nextPage);
            params.append('per_page', this.itemsPerPage);
            
            const response = await fetch(`/admin/duplicates/filter?${params}`);
            const data = await response.json();
            
            if (data.success && data.duplicate_groups.length > 0) {
                // Append new results to existing ones
                this.filteredGroups = this.filteredGroups.concat(data.duplicate_groups);
                this.pagination = data.pagination;
                
                // Render new groups
                const container = $('#duplicateGroupsContainer');
                data.duplicate_groups.forEach((group, index) => {
                    const groupHtml = this.renderFilteredDuplicateGroup(group, this.filteredGroups.length - data.duplicate_groups.length + index);
                    container.append(groupHtml);
                });
            }
        } catch (error) {
            console.error('Error loading more results:', error);
        } finally {
            this.isLoading = false;
        }
    }
    
    // Enhanced error handling and user feedback
    showSuccess(message) {
        this.showToast(message, 'success');
    }
    
    showError(message) {
        this.showToast(message, 'error');
    }
    
    showToast(message, type = 'info') {
        const toastClass = type === 'success' ? 'alert-success' : type === 'error' ? 'alert-danger' : 'alert-info';
        const iconClass = type === 'success' ? 'fa-check-circle' : type === 'error' ? 'fa-exclamation-circle' : 'fa-info-circle';
        
        const toastHtml = `
            <div class="alert ${toastClass} alert-dismissible fade show toast-notification" role="alert" style="position: fixed; top: 20px; right: 20px; z-index: 9999; min-width: 300px;">
                <i class="fas ${iconClass}"></i> ${message}
                <button type="button" class="close" data-dismiss="alert">
                    <span>&times;</span>
                </button>
            </div>
        `;
        
        $('body').append(toastHtml);
        
        // Auto-dismiss after 5 seconds
        setTimeout(() => {
            $('.toast-notification').alert('close');
        }, 5000);
    }
    
    initializePerformanceSettings() {
        // Detect if we should use performance mode based on dataset size
        this.performanceMode = false; // Will be set based on data size
        this.virtualScrollEnabled = false; // Will be enabled for large datasets
        
        // Add performance monitoring
        this.loadCacheStats();
    }
    
    async loadCacheStats() {
        try {
            const response = await fetch('/admin/duplicates/cache/stats');
            const data = await response.json();
            
            if (data.success) {
                this.updatePerformanceUI(data);
                
                // Enable performance mode if database is large
                if (data.database_stats.total_tracks > 5000) {
                    this.performanceMode = true;
                    this.itemsPerPage = 5; // Smaller page size for large datasets
                }
            }
        } catch (error) {
            console.log('Cache stats not available:', error);
        }
    }
    
    updatePerformanceUI(data) {
        // Add performance indicators to the UI
        const cacheStats = data.cache_stats;
        const dbStats = data.database_stats;
        
        // Show cache status in console for debugging
        if (window.console && console.log) {
            console.log('Performance Stats:', {
                'Cache Entries': cacheStats.valid_entries,
                'Database Tracks': dbStats.total_tracks,
                'Indexes Available': dbStats.index_count,
                'Performance Optimized': dbStats.performance_optimized
            });
        }
        
        // Add performance badge to header if needed
        if (!dbStats.performance_optimized) {
            this.showPerformanceWarning();
        }
    }
    
    showPerformanceWarning() {
        const warningHtml = `
            <div class="alert alert-warning alert-dismissible fade show" role="alert" id="performanceWarning">
                <i class="fas fa-exclamation-triangle"></i>
                <strong>Performance Notice:</strong> Database indexes are not optimized. 
                <button type="button" class="btn btn-sm btn-outline-warning ml-2" onclick="duplicateManager.optimizePerformance()">
                    Optimize Now
                </button>
                <button type="button" class="close" data-dismiss="alert">
                    <span>&times;</span>
                </button>
            </div>
        `;
        
        $('.container-fluid').prepend(warningHtml);
    }
    
    async optimizePerformance() {
        try {
            this.showProgressModal('Optimizing Performance...', 'Please wait while we optimize the database for better performance.');
            
            const response = await fetch('/admin/duplicates/performance/optimize', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                }
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showSuccess('Performance optimization completed: ' + result.optimizations_applied.join(', '));
                $('#performanceWarning').alert('close');
                
                // Reload cache stats
                setTimeout(() => this.loadCacheStats(), 1000);
            } else {
                this.showError('Performance optimization failed: ' + result.error);
            }
        } catch (error) {
            console.error('Error optimizing performance:', error);
            this.showError('Network error during performance optimization');
        } finally {
            this.hideProgressModal();
        }
    }
    
    async clearCache() {
        try {
            const response = await fetch('/admin/duplicates/cache/clear', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                }
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showSuccess('Cache cleared successfully');
                // Reload cache stats
                this.loadCacheStats();
            } else {
                this.showError('Failed to clear cache: ' + result.error);
            }
        } catch (error) {
            console.error('Error clearing cache:', error);
            this.showError('Network error while clearing cache');
        }
    }
    
    refreshData() {
        // Refresh the duplicate data by re-running the scan
        this.scanForDuplicates();
    }
    
    /**
     * Remove deleted tracks from current results without triggering a full re-analysis
     */
    removeDeletedTracksFromResults(deletedTrackIds) {
        // Remove tracks from duplicate groups
        this.duplicateGroups = this.duplicateGroups.map(group => {
            // Filter out deleted tracks from canonical and duplicates
            const updatedGroup = {
                ...group,
                duplicates: group.duplicates.filter(track => !deletedTrackIds.includes(track.id))
            };
            
            // If canonical track was deleted, promote the first duplicate
            if (deletedTrackIds.includes(group.canonical_song.id)) {
                if (updatedGroup.duplicates.length > 0) {
                    updatedGroup.canonical_song = updatedGroup.duplicates[0];
                    updatedGroup.duplicates = updatedGroup.duplicates.slice(1);
                } else {
                    // No tracks left in group, mark for removal
                    return null;
                }
            }
            
            return updatedGroup;
        }).filter(group => group !== null && group.duplicates.length > 0); // Remove empty groups
        
        // Update filtered groups
        this.filteredGroups = this.duplicateGroups;
        
        // Update statistics
        this.updateStatistics();
    }
    
    async applyFiltersWithCancellation() {
        // Cancel previous request if still pending
        if (this.lastFilterRequest) {
            this.lastFilterRequest.abort();
        }
        
        if (this.isLoading) return;
        
        this.isLoading = true;
        this.showFilterLoading();
        
        try {
            const searchTerm = $('#searchInput').val().trim();
            const sortBy = $('#sortBy').val();
            const minConfidence = parseFloat($('#confidenceFilter').val());
            
            const params = new URLSearchParams();
            if (searchTerm) params.append('search', searchTerm);
            if (sortBy) params.append('sort_by', sortBy);
            if (minConfidence > 0) params.append('min_confidence', minConfidence);
            params.append('page', this.currentPage);
            params.append('per_page', this.itemsPerPage);
            params.append('optimize', 'true'); // Always use optimization for real-time filtering
            
            // Create AbortController for request cancellation
            const controller = new AbortController();
            this.lastFilterRequest = controller;
            
            // Add timeout to the request
            const timeoutId = setTimeout(() => {
                controller.abort();
            }, 10000); // 10 second timeout
            
            const response = await fetch(`/admin/duplicates/filter?${params}`, {
                signal: controller.signal,
                headers: {
                    'Cache-Control': 'no-cache',
                    'Pragma': 'no-cache'
                }
            });
            
            clearTimeout(timeoutId);
            this.lastFilterRequest = null;
            
            if (response.status === 408) {
                // Request timeout
                this.showError('Request timed out. Try reducing your search scope or clearing filters.');
                return;
            }
            
            const data = await response.json();
            
            if (data.success) {
                this.filteredGroups = data.duplicate_groups || [];
                this.pagination = data.pagination || {};
                this.renderFilteredGroups();
                
                // Update URL with current filters
                this.updateUrlParams(params);
                
                // Update performance metrics if available
                if (data.performance_metrics) {
                    this.updatePerformanceMetrics(data.performance_metrics);
                }
            } else {
                if (data.timed_out) {
                    this.showError('Search timed out. Try using more specific search terms.');
                } else {
                    this.showError('Error filtering duplicates: ' + (data.error || 'Unknown error'));
                }
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                console.log('Filter request was cancelled');
                return;
            }
            console.error('Error filtering duplicates:', error);
            this.showError('Network error while filtering duplicates');
        } finally {
            this.isLoading = false;
            this.hideFilterLoading();
        }
    }
    
    // ============================================================================
    // PERSISTENCE INTEGRATION METHODS
    // ============================================================================
    
    /**
     * Check for existing analysis on page load
     */
    async checkForExistingAnalysis() {
        try {
            const response = await fetch('/admin/duplicates/analyses?limit=1');
            const data = await response.json();
            
            if (data.success && data.analyses && data.analyses.length > 0) {
                const latestAnalysis = data.analyses[0];
                
                // Set current analysis ID
                this.currentAnalysisId = latestAnalysis.analysis_id;
                
                // Notify persistence manager
                if (window.duplicatePersistenceManager) {
                    window.duplicatePersistenceManager.setCurrentAnalysisId(latestAnalysis.analysis_id);
                    await window.duplicatePersistenceManager.checkAnalysisAge(latestAnalysis.analysis_id);
                }
            }
        } catch (error) {
            console.error('Error checking for existing analysis:', error);
        }
    }
    
    /**
     * Load analysis results from persistence data
     */
    loadAnalysisResults(analysisData) {
        // Clear all progress states and modals
        this.clearProgressState();
        
        this.duplicateGroups = analysisData.duplicate_groups || [];
        this.filteredGroups = this.duplicateGroups;
        this.currentAnalysisId = analysisData.analysis_id;
        
        // Update statistics if available
        if (analysisData.analysis) {
            this.updateStatistics(analysisData.analysis);
        }
        
        // Show results
        if (this.duplicateGroups.length === 0) {
            this.showNoResults();
        } else {
            this.showDuplicateGroups();
            this.renderDuplicateGroups();
        }
        
        // Hide age banner if this is a fresh analysis
        if (analysisData.is_fresh) {
            if (window.duplicatePersistenceManager) {
                window.duplicatePersistenceManager.hideAgeBanner();
            }
        }
    }
    
    /**
     * Enhanced scan for duplicates with persistence integration
     */
    async scanForDuplicatesWithPersistence() {
        if (this.isLoading) return;
        
        this.isLoading = true;
        
        try {
            const searchTerm = $('#searchInput').val().trim();
            const sortBy = $('#sortBy').val();
            const minConfidence = parseFloat($('#confidenceFilter').val());
            
            const params = new URLSearchParams();
            if (searchTerm) params.append('search', searchTerm);
            if (sortBy) params.append('sort_by', sortBy);
            if (minConfidence > 0) params.append('min_confidence', minConfidence);
            params.append('force_refresh', 'true'); // Force new analysis
            
            // Use the persistence endpoint
            const response = await fetch(`/admin/duplicates/analyze-with-persistence?${params}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                }
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.currentAnalysisId = data.analysis_id;
                
                // Start progress tracking
                if (window.duplicatePersistenceManager) {
                    window.duplicatePersistenceManager.setCurrentAnalysisId(data.analysis_id);
                    window.duplicatePersistenceManager.startProgressTracking(data.analysis_id);
                }
            } else {
                this.showError('Error starting analysis: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            console.error('Error starting analysis with persistence:', error);
            this.showError('Network error starting analysis');
        } finally {
            this.isLoading = false;
        }
    }
    
    /**
     * Override the original scanForDuplicates to use persistence
     */
    async scanForDuplicates() {
        // Check if persistence is available
        if (window.duplicatePersistenceManager) {
            return this.scanForDuplicatesWithPersistence();
        }
        
        // Fallback to original implementation
        return this.originalScanForDuplicates();
    }
    
    /**
     * Store original scan method as fallback
     */
    async originalScanForDuplicates() {
        if (this.isLoading) return;
        
        this.isLoading = true;
        this.showLoading();
        
        try {
            const searchTerm = $('#searchInput').val().trim();
            const sortBy = $('#sortBy').val();
            const minConfidence = parseFloat($('#confidenceFilter').val());
            
            const params = new URLSearchParams();
            if (searchTerm) params.append('search', searchTerm);
            if (sortBy) params.append('sort_by', sortBy);
            if (minConfidence > 0) params.append('min_confidence', minConfidence);
            params.append('page', this.currentPage);
            params.append('per_page', this.itemsPerPage);
            
            const response = await fetch(`/admin/duplicates/analyze?${params}`);
            const data = await response.json();
            
            if (data.success) {
                this.duplicateGroups = data.duplicate_groups || [];
                this.itunesAvailable = data.itunes_available || false;
                this.pagination = data.pagination || {};
                this.updateStatistics(data.analysis || {});
                
                if (this.duplicateGroups.length === 0) {
                    this.showNoResults();
                } else {
                    this.showDuplicateGroups();
                    this.renderDuplicateGroups();
                }
            } else {
                this.showError('Error scanning for duplicates: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            console.error('Error scanning for duplicates:', error);
            this.showError('Network error while scanning for duplicates');
        } finally {
            this.isLoading = false;
            this.hideLoading();
        }
    }
    
    /**
     * Get current analysis ID
     */
    getCurrentAnalysisId() {
        return this.currentAnalysisId;
    }
    
    /**
     * Set current analysis ID
     */
    setCurrentAnalysisId(analysisId) {
        this.currentAnalysisId = analysisId;
    }
}

// Utility function for debouncing
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Initialize when document is ready
$(document).ready(function() {
    const duplicateManager = new DuplicateManager();
    
    // Make it globally accessible for persistence integration
    window.duplicateManager = duplicateManager;
    
    // Handle checkbox changes
    $(document).on('change', '.duplicate-checkbox', function() {
        const trackId = parseInt($(this).data('track-id'));
        if ($(this).is(':checked')) {
            duplicateManager.selectedDuplicates.add(trackId);
        } else {
            duplicateManager.selectedDuplicates.delete(trackId);
        }
        duplicateManager.updateSelectedCount();
    });
    
    // Handle group toggle
    $(document).on('click', '.toggle-group', function() {
        const target = $(this).data('target');
        const icon = $(this).find('i');
        
        $(target).collapse('toggle');
        
        $(target).on('shown.bs.collapse', function() {
            icon.removeClass('fa-chevron-down').addClass('fa-chevron-up');
            $(this).find('button').html('<i class="fas fa-chevron-up"></i> Hide Details');
        });
        
        $(target).on('hidden.bs.collapse', function() {
            icon.removeClass('fa-chevron-up').addClass('fa-chevron-down');
            $(this).find('button').html('<i class="fas fa-chevron-down"></i> Show Details');
        });
    });
    
    // Handle individual delete buttons
    $(document).on('click', '.individual-delete-btn', function() {
        const trackId = parseInt($(this).data('track-id'));
        const songName = $(this).data('song');
        const artistName = $(this).data('artist');
        
        duplicateManager.deleteIndividualTrack(trackId, songName, artistName);
    });
    
    // Handle pagination clicks
    $(document).on('click', '#paginationList .page-link', function(e) {
        e.preventDefault();
        const page = parseInt($(this).data('page'));
        if (page && page !== duplicateManager.currentPage) {
            duplicateManager.currentPage = page;
            duplicateManager.renderDuplicateGroups();
        }
    });
});
