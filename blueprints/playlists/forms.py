# blueprints/playlists/forms.py
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, IntegerField, SelectField
from wtforms.validators import DataRequired, NumberRange

class PlaylistGeneratorForm(FlaskForm):
    playlist_name = StringField('Playlist Name', validators=[DataRequired()])
    playlist_length = IntegerField('Playlist Length (minutes)', validators=[DataRequired(), NumberRange(min=1)])
    minimum_recent_add_playcount = IntegerField('Minimum Recent Add Playcount', validators=[DataRequired(), NumberRange(min=0)])
    submit = SubmitField('Generate Playlist')
