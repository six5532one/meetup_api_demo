from flask.ext.wtf import Form
from wtforms import StringField
from wtforms.validators import DataRequired

class PhoneForm(Form):
    phone = StringField('phone', validators=[DataRequired()])
