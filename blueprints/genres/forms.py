from flask_wtf import FlaskForm
from wtforms import StringField, SelectMultipleField, SubmitField
from wtforms.validators import DataRequired

class GenreForm(FlaskForm):
    name = StringField('Genre Name', validators=[DataRequired()])
    submit = SubmitField('Save')

class AssignGenreForm(FlaskForm):
    genres = SelectMultipleField('Genres', coerce=int)
    submit = SubmitField('Assign')
