# Copyright 2013. Amazon Web Services, Inc. All Rights Reserved.
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import requests
import logging
import json
import boto.dynamodb
import flask

from flask import request, Response
from twilio.rest import TwilioRestClient


# Create and configure the Flask app
application = flask.Flask(__name__)
application.config.from_object('default_config')
application.debug = application.config['FLASK_DEBUG'] in ['true', 'True']

@application.route('/checkin', methods=['POST'])
def process_checkin():    
    try:
        decoded = base64.b64decode(request.get_data())
        data = json.loads(decoded)

        # extract foursquare_uid, lat, lng from message
        lat = data["lat"]
        lng = data["lng"]
        fid = data["fid"]
        
        # request recent and upcoming events near lat, lon from Meetup's API
        payload = {"sign": "true", 
                   "key": application.config['MEETUP_APIKEY'],
                   "order": "distance",
                   "lat": lat,
                   "lon": lng}
        meetup_api_host = application.config['MEETUP_API_HOST']
        endpoint = '/2/open_events'
        r = requests.get("{host}{path}".format(host=meetup_api_host, path=endpoint), params=payload)
        response = r.json()

        try:
            events = response['results']
            # grab the event nearest to the checkin
            result = events[0] if len(events) > 0 else None
            dist_threshold = 0.05
            accepted_event_statuses = ["upcoming", "past"]
            if (result is not None) and (result.get("distance", 1000) <= dist_threshold) and (result.get("status", "") in accepted_event_statuses):
                try:
                    status = result["status"]
                    event_name = result["name"]
                    event_url = result["event_url"]
                    group_name = result["group"]["name"]
                    # construct notification text
                    notify_upcoming = "{gname} is hosting an upcoming Meetup here: {ename}\n{eurl}".format(gname=group_name, ename=event_name, eurl=event_url)
                    notify_past = "{gname} recently had a Meetup here: {ename}\n{eurl}".format(gname=group_name, ename=event_name, eurl=event_url)
                    notification = notify_upcoming if status == "upcoming" else notify_past
                    
                    # get Twilio client
                    account_sid = application.config['TWILIO_ACCOUNT_SID']
                    auth_token = application.config['TWILIO_AUTH_TOKEN']
                    client = TwilioRestClient(account_sid, auth_token)
                    twilio_from = application.config['TWILIO_SENDER']
                    # look up the phone number that corresponds to this Foursquare user id
                    conn = boto.dynamodb.connect_to_region(application.config['AWS_REGION'], 
                                            aws_access_key_id=application.config['AWS_ACCESS'], 
                                            aws_secret_access_key=application.config['AWS_SECRET'])
                    phone_nums = conn.get_table('phonenums')
                    to_phone_num = phone_nums.get_item(hash_key=fid)['phone']
                    # send SMS
                    message = client.messages.create(to="+{}".format(to_phone_num), 
                                                     from_=twilio_from, 
                                                     body=notification)
                # not enough information to send notification
                except KeyError, e:
                    logging.exception(str(e))
                    response = Response(str(e), status=500) 

        # request not sucessful
        # key "results" is not in `response` object
        except KeyError:
            logging.exception(json.dumps(response))
            response = Response(json.dumps(response), status=500)

        # request succeeded
        response = Response("", status=200)

    # failed to parse body of the POST request
    except Exception, e:
        logging.exception(str(e))
        response = Response(str(e), status=500)
    
    # successfully parsed POST data
    response = Response("", status=200)
    return response


if __name__ == '__main__':
    application.run(host='0.0.0.0')
