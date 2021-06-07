import datetime
import json
from datetime import date

import google.cloud.firestore
import requests
from flask import escape


def fetch_data_from_api(url):
    payload = {}
    headers = {
        'x-rapidapi-host': 'v3.football.api-sports.io',
        'x-rapidapi-key': '5453c6e17010446f88dab41a62c97a53'
    }

    response = requests.request("GET", url, headers=headers, data=payload)

    obj = json.loads(response.text)

    return obj


# to deploy function from console: 'gcloud functions deploy update_fixtures'
def update_fixtures(request):
    request_args = request.args

    # check arg 'league_id'. mandatory
    if request_args and 'league_id' in request_args:
        league_id = request_args['league_id']
    else:
        msg = 'Error: league_id parameter is missing'
        print(msg)
        return msg

    # check args 'from' and 'to'. no mandatory
    if request_args and 'from' in request_args and 'to' in request_args:
        param_from = request_args['from']
        param_to = request_args['to']
        date_filter = True
    else:
        date_filter = False

    # build url from request args
    if date_filter:
        url = f'https://v3.football.api-sports.io/fixtures?season=2020&league={league_id}&from={param_from}&to={param_to}'
    else:
        url = f'https://v3.football.api-sports.io/fixtures?season=2020&league={league_id}'

    # connect db
    db = google.cloud.firestore.Client()
    batch = db.batch()

    # get json response
    obj = fetch_data_from_api(url=url)
    response = obj['response']
    results_count = obj['results']

    count = 0

    for json_obj in response:
        count = count + 1

        fixture_id = json_obj["fixture"]["id"]
        fixture_date = (json_obj["fixture"]["date"]).split(':')[0]

        print(f'{fixture_date}-{fixture_id}, {count / results_count * 100:.2f}%')

        doc_ref = db.collection(u'fixtures').document(f'{fixture_id}')

        fixture = json_obj["fixture"]
        league = json_obj["league"]
        teams = json_obj["teams"]
        goals = json_obj["goals"]
        score = json_obj["score"]

        # each batch.set is 1 operation
        batch.set(doc_ref, {
            'fixture': fixture,
            'league': league,
            'teams': teams,
            'goals': goals,
            'score': score,
        })

        # commit every X documents for better performance (max is 500 operations per batch)
        if count % 400 == 0:
            batch.commit()

    batch.commit()  # commit the rest of oeprations

    # print a summary line
    if date_filter:
        res = f'Success for {count} fixtures: league_id={league_id}, from={param_from}, to={param_to}'
    else:
        res = f'Success for {count} fixtures: league_id={league_id}'
    print(res)
    return res


# to deploy function from console: 'gcloud functions deploy cron'
def cron(request):
    request_args = request.args

    # check arg 'league_id'. mandatory
    if request_args and 'league_id' in request_args:
        league_id = request_args['league_id']
    else:
        msg = 'Error: league_id parameter is missing'
        print(msg)
        return msg

    today = date.today()
    minus_one_day = datetime.timedelta(days=-1)
    yesterday = today + minus_one_day

    url = f'https://us-central1-better-gsts.cloudfunctions.net/update_fixtures' \
          f'?league_id={league_id}&from={yesterday.isoformat()}&to={today.isoformat()}'

    url2 = f'https://us-central1-better-gsts.cloudfunctions.net/tag_tips' \
           f'?date={yesterday.isoformat()}'

    payload = {}
    headers = {
        'x-rapidapi-host': 'v3.football.api-sports.io',
        'x-rapidapi-key': '5453c6e17010446f88dab41a62c97a53'
    }

    response = requests.request("GET", url2, headers=headers, data=payload)
    print(response.text)

    response = requests.request("GET", url, headers=headers, data=payload)
    return response.text


def skip_fixture(data):
    status = data['fixture']['status']['short']
    if status == 'NS' or status == 'PST' or status == 'TBD':
        return True
    return False


def get_winner_from_fixture(fixtureID):
    db = google.cloud.firestore.Client()
    fixtures_ref = db.collection(u'fixtures')

    ref = fixtures_ref \
        .where('fixture.id', '==', fixtureID)

    query = ref.stream()

    for doc in query:
        data = doc.to_dict()

        if skip_fixture(data):
            return None

        home = data['teams']['home']['winner']
        away = data['teams']['away']['winner']

        if home:
            return 1
        if away:
            return 2
        return 0


# to deploy function from console: 'gcloud functions deploy tag_tips'
def tag_tips(request):
    request_args = request.args

    # check arg 'league_id'. mandatory
    if request_args and 'date' in request_args:
        date = request_args['date']
        year = date.split('-')[0]
        month = date.split('-')[1]
        day = date.split('-')[2]
    else:
        date = datetime.datetime.now()
        iso = date.__str__().split(' ')[0]
        year = iso.split('-')[0]
        month = iso.split('-')[1]
        day = iso.split('-')[2]

    db = google.cloud.firestore.Client()

    # Query data
    tips_ref = db.collection('eventTips')
    ref = tips_ref \
        .where('created', '>=', datetime.datetime(int(year), int(month), int(day)))

    docs = ref.stream()

    cache = {}
    count = 0

    for doc in docs:
        count = count + 1
        data = doc.to_dict()

        fixtureID = data['fixture']
        print("ID:", fixtureID)

        if fixtureID in cache:
            winner = cache[fixtureID]
        else:
            winner = get_winner_from_fixture(fixtureID)
            cache[fixtureID] = winner

        print("query count:", count, "cache size:", len(cache))

        if winner is not None:
            hit = winner == data['tipValue']

            doc_ref = db.collection(u'eventTips').document(doc.id)

            doc_ref.set({
                'isHit': hit
            }, merge=True)

    retval = 'date:{0}-{1}-{2}, query count:{3}, cache size:{4}'.format(year, month, day, count, len(cache))
    return retval


def hello_http(request):
    """HTTP Cloud Function.
    Args:
        request (flask.Request): The request object.
        <https://flask.palletsprojects.com/en/1.1.x/api/#incoming-request-data>
    Returns:
        The response text, or any set of values that can be turned into a
        Response object using `make_response`
        <https://flask.palletsprojects.com/en/1.1.x/api/#flask.make_response>.
    """
    request_json = request.get_json(silent=True)
    request_args = request.args

    if request_json and 'name' in request_json:
        name = request_json['name']
    elif request_args and 'name' in request_args:
        name = request_args['name']
    else:
        name = 'World'
    return 'Hello {}!'.format(escape(name))
