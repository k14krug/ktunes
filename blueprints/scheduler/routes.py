from flask import jsonify, render_template, request, redirect, url_for, flash
from . import scheduler_bp  
from extensions import scheduler, job_status
import app_context_holder
from config_loader import load_config, save_config
from datetime import datetime, timezone

@scheduler_bp.route('/jobs', methods=['GET'])
def list_jobs():
    """
    List all scheduled jobs.
    """
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger)
        })
    return jsonify({"jobs": jobs})


@scheduler_bp.route('/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    """f
    Get details of a specific job by ID.
    """
    job = scheduler.get_job(job_id)
    if not job:
        return jsonify({"error": f"Job with ID {job_id} not found"}), 404

    return jsonify({
        "id": job.id,
        "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
        "trigger": str(job.trigger)
    })

#

@scheduler_bp.route('/jobs/<job_id>', methods=['DELETE', 'POST'])
def delete_job(job_id):
    """
    Remove a specific job by ID.
    """
    job = scheduler.get_job(job_id)
    if not job:
        return jsonify({"error": f"Job with ID {job_id} not found"}), 404

    scheduler.remove_job(job_id)
    flash(f"Job {job_id} removed successfully", "success")
    return redirect(url_for('apscheduler.dashboard'))


@scheduler_bp.route('/jobs', methods=['POST'])
def add_job():
    """
    Example endpoint to add a job.
    Adjust the parameters to fit your requirements.
    """
    # Example of adding a job
    scheduler.add_job(
        id="test_job",
        func='tasks.scheduled_tasks:export_default_playlist_to_spotify_task',
        trigger="interval",
        minutes=10,
        replace_existing=True
    )
    return jsonify({"message": "Test job added successfully"})

@scheduler_bp.route('/dashboard', methods=['GET'])
def dashboard():
    jobs = scheduler.get_jobs()
    # Pass both jobs and their statuses to the template
    return render_template('dashboard.html', jobs=jobs, job_status=job_status, scheduled_tasks=app_context_holder.app.config.get('scheduled_tasks', {}))

@scheduler_bp.route('/toggle_task/<task_id>', methods=['POST'])
def toggle_task(task_id):
    from app import register_job
    action = request.form.get('action')
    config = load_config()
    
    if task_id in config.get('scheduled_tasks', {}):
        is_enabled = action == 'enable'
        config['scheduled_tasks'][task_id]['enabled'] = is_enabled
        save_config(config)
        
        # Update the app's config in memory
        app_context_holder.app.config['scheduled_tasks'][task_id]['enabled'] = is_enabled

        if is_enabled:
            register_job(app_context_holder.app, task_id)
            flash(f'Task {task_id} has been enabled.', 'success')
        else:
            if scheduler.get_job(task_id):
                scheduler.remove_job(task_id)
            flash(f'Task {task_id} has been disabled.', 'warning')
            
    else:
        flash(f'Task {task_id} not found in configuration.', 'danger')
        
    return redirect(url_for('apscheduler.dashboard'))

@scheduler_bp.route('/run_job/<job_id>', methods=['POST'])
def run_job(job_id):
    """Manually trigger a job to run immediately."""
    job = scheduler.get_job(job_id)
    if job:
        job.modify(next_run_time=datetime.now(timezone.utc))
        flash(f'Job "{job_id}" has been triggered to run now.', 'info')
    else:
        flash(f'Job "{job_id}" not found.', 'danger')
    return redirect(url_for('apscheduler.dashboard'))


