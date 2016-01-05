import json
import requests
import boto.dynamodb
import boto.sqs

from boto.sqs.message import Message
from forms import PhoneForm
from flask import (Flask, flash, session, redirect, url_for,
                   render_template, request, jsonify)
from datetime import datetime
from urllib2 import HTTPError
from rauth.service import OAuth2Service

application = Flask(__name__)
application.config.from_object('config')
conn = boto.sqs.connect_to_region(application.config['AWS_REGION'])
q = conn.create_queue('checkins')

@application.route('/')
def index():
    """
    Initiate Foursquare OAuth dance if the user 
    hasn't authorized this application. Otherwise, 
    proceed to get their phone number.
    """
    if connected("foursquare"):
        return redirect(url_for('phone'))
    else:
        return render_template('index.html')


@application.route('/phone', methods=['GET', 'POST'])
def phone():
    """
    Save the user's phone number if it has been posted
    and validated. Otherwise, render the form for the user
    to submit their phone number.
    """
    form = PhoneForm()
    if form.validate_on_submit():
        # save a record of the user's Foursquare user id and phone number
        conn = boto.dynamodb.connect_to_region(application.config['AWS_REGION'], 
                                               aws_access_key_id=application.config['AWS_ACCESS'], 
                                               aws_secret_access_key=application.config['AWS_SECRET'])
        phone_nums = conn.get_table('phonenums')
        item_data = {'phone': form.phone.data}
        item = phone_nums.new_item(hash_key=session['foursquare_id'], attrs=item_data)
        item.put()
        return redirect(url_for('done'))
    return render_template('phone.html', form=form, name=session["foursquare_uname"])


@application.route('/done')
def done():
    """Let the user know they finished the sign-up process."""
    return render_template('done.html', name=session["foursquare_uname"])


@application.route('/signout')
def signout():
    """End the user session."""
    empty_credentials()
    flash('Signed out')
    return redirect(url_for('index'))


@application.route('/connect_foursquare')
def connect_foursquare():
    """Connect the user with foursquare.com."""
    foursquare = get_foursquare_service_container()
    #redirect_uri = url_for("auth_foursquare")
    redirect_uri = "http://www.theresameetuphere.com/auth_foursquare"
    params = {'response_type': 'code',
              'redirect_uri': redirect_uri}
    authorize_url = foursquare.get_authorize_url(**params)
    return redirect(authorize_url)


@application.route('/auth_foursquare')
def auth_foursquare():
    """ 
    foursquare.com redirects the user here after
    the user is prompted for authentication.
    If the user authorized this application 
    to access check-ins, request an access token.
    """
    # check to make sure the user authorized the request
    if not 'code' in request.args:
        flash('You did not authorize the request')
        return redirect(url_for('index'))
    else:
        # make a request for the access token credentials using code
        foursquare = get_foursquare_service_container()
        #redirect_uri = url_for("auth_foursquare", _external=True)
        redirect_uri = "http://www.theresameetuphere.com/auth_foursquare"
        data = dict(code=request.args['code'],
                    redirect_uri=redirect_uri,
                    grant_type='authorization_code')
        response = foursquare.get_raw_access_token(data=data).json()
        access_token = response['access_token']
        # add Foursquare access token to session
        session['foursquare_credentials'] = {
            "access_token": access_token
        }
        # get Foursquare user id of authorizing user 
        payload = {"v": "20140806", "oauth_token": access_token}
        r = requests.get("https://api.foursquare.com/v2/users/self", params=payload)

        foursquare_id = r.json()["response"]["user"]["id"]
        foursquare_uname = r.json()["response"]["user"]["firstName"]
        session["foursquare_id"] = foursquare_id
        session["foursquare_uname"] = foursquare_uname
        flash("You're connected to Foursquare!")
        return redirect(url_for('index'))


@application.route('/handle_push', methods=['POST'])
def handle_push():
    """
    Receive data from Foursquare every time an 
    authorizing user checks in to a venue on Swarm.
    """
    checkin = json.loads(request.form['checkin'])
    foursquare_uid = checkin["user"]["id"]
    lat = checkin["venue"]["location"].get("lat", "")
    lng = checkin["venue"]["location"].get("lng", "")
    if (lat is not None) and (lng is not None):
        # write to a message queue maintained by AWS SQS
        m = Message()
        msg_body = {"fid": foursquare_uid,
                     "lat": lat,
                     "lng": lng}
        m.set_body(json.dumps(msg_body))
        q.write(m)
    # return 200 OK before Foursquare's push request times out
    response = jsonify(message="received")
    response.status_code = 200
    return response


@application.errorhandler(404)
def not_found(error):
    return render_template('not_found.html')


@application.errorhandler(500)
def server_error(error):
    return render_template('app_error.html',
                           error = 'Server error %s' % error)


@application.template_filter('millidate')
def millidate_filter(t):
   return datetime.fromtimestamp(t/1000).strftime('%a %b %d @ %I:%M%p')


application.secret_key = application.config['COOKIE_SECRET']


# helpers
def get_foursquare_service_container():
    """
    Return a service wrapper that provides
    OAuth 2.0 flow methods.
    """
    client_id = application.config['FOURSQUARE_CLIENT_ID']
    client_secret = application.config['FOURSQUARE_CLIENT_SECRET']
    service_container = OAuth2Service(client_id=client_id,
                                client_secret=client_secret,
                                name='foursquare',
                                authorize_url='https://foursquare.com/oauth2/authenticate',
                                access_token_url='https://foursquare.com/oauth2/access_token',
                                base_url='https://api.foursquare.com/v2/')
    return service_container


def empty_credentials():
    """
    Remove all provider credentials 
    currently stored in the session.
    """
    for provider in ["foursquare"]: 
        session.pop('{}_credentials'.format(provider), None)


def connected(provider):
  """
  Return True if the current user is connected
  to the service provider. Otherwise, return False.
  """
  return '{}_credentials'.format(provider) in session


if __name__ == '__main__':
    application.run(debug=True)
