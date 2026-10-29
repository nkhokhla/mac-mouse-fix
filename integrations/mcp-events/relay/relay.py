#!/usr/bin/env python3
"""Relay trusted GitHub Actions events into the private MCP Events bridge.

No polling timer. API reads happen only after an event, to obtain current PR facts.
The workflow checks out this script from master, never from a PR head.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = 'nkhokhla/mac-mouse-fix'
BRANCH = 'automation/upstream-sync'
SELF_PREFIX = '[mcp-upstream]'

def api(path):
    request = urllib.request.Request(
        'https://api.github.com/repos/' + REPOSITORY + '/' + path,
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                 'Accept': 'application/vnd.github+json',
                 'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)

def candidates(name, payload, get=api):
    if name == 'workflow_dispatch':
        number = str(payload.get('inputs', {}).get('pull_request_number', '3'))
        if not number.isdecimal() or int(number) <= 0:
            raise ValueError('Expected a positive PR number')
        return [get('pulls/' + number)]
    if name == 'workflow_run':
        run = payload.get('workflow_run', {})
        if run.get('name') != 'Sync upstream' or run.get('head_repository', {}).get('full_name') != REPOSITORY or run.get('head_branch') != 'master':
            return []
        # The sync workflow uses GITHUB_TOKEN, whose generated PR events may be
        # suppressed. workflow_run is the reliable event boundary for that case.
        return get('pulls?state=open&head=' + urllib.parse.quote('nkhokhla:' + BRANCH, safe='') + '&base=master&per_page=100')
    number = payload.get('pull_request', {}).get('number')
    if name == 'issue_comment':
        issue = payload.get('issue', {})
        if not issue.get('pull_request'):
            return []
        number = issue.get('number')
    if not isinstance(number, int) or number <= 0:
        return []
    if name in ('pull_request_review', 'pull_request_review_comment', 'issue_comment'):
        actor = (payload.get('review') or payload.get('comment') or {}).get('user', {})
        if actor.get('type') != 'User' or str(actor.get('login', '')).endswith('[bot]'):
            return []
    return [get('pulls/' + str(number))]

def event_for(name, payload, pr, run_id, attempt, get=api):
    if pr.get('state') != 'open' or pr.get('draft'):
        return None
    head, base = pr.get('head', {}), pr.get('base', {})
    if head.get('ref') != BRANCH or head.get('repo', {}).get('full_name') != REPOSITORY or base.get('ref') != 'master' or base.get('repo', {}).get('full_name') != REPOSITORY:
        return None
    action = payload.get('action', '')
    if name == 'pull_request_target' and action == 'synchronize':
        commit = get('commits/' + head['sha'])
        if commit.get('commit', {}).get('message', '').startswith(SELF_PREFIX):
            return None  # Agent repairs must not wake the same agent indefinitely.
    reasons = {'workflow_run': 'sync_completed', 'workflow_dispatch': 'bootstrap',
               'issue_comment': 'feedback', 'pull_request_review': 'feedback',
               'pull_request_review_comment': 'feedback'}
    reason = reasons.get(name, {'opened': 'pr_opened', 'reopened': 'pr_reopened'}.get(action, 'pr_updated'))
    source = payload.get('review') or payload.get('comment') or payload.get('workflow_run') or {}
    source_id = str(source.get('id') or run_id)
    # The same workflow attempt always produces the same identity and timestamp.
    # Reruns intentionally get a new ID and can replay a failed delivery.
    identity = f'{REPOSITORY}:{run_id}:{attempt}:{pr["number"]}:{head["sha"]}'
    timestamp = source.get('submitted_at') or source.get('created_at') or pr['updated_at']
    return {'eventId': 'evt_' + hashlib.sha256(identity.encode()).hexdigest(),
            'name': 'upstream_sync.attention', 'timestamp': timestamp, 'cursor': None,
            'data': {'repository': REPOSITORY, 'pull_request_number': pr['number'],
                     'url': f'https://github.com/{REPOSITORY}/pull/{pr["number"]}',
                     'title': pr['title'][:1000], 'head_sha': head['sha'], 'base_sha': base['sha'],
                     'head_branch': BRANCH, 'base_branch': 'master', 'reason': reason,
                     'source_event': name, 'source_id': source_id,
                     'source_url': source.get('html_url') or f'https://github.com/{REPOSITORY}/actions/runs/{run_id}'}}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def deliver(event, endpoint, token, opener=None, sleep=time.sleep):
    opener = opener or urllib.request.build_opener(NoRedirect)
    data = json.dumps(event, separators=(',', ':')).encode()
    for delay in (0, 2, 8, 20, 45, 60):
        if delay:
            sleep(delay)
        request = urllib.request.Request(endpoint + '/api/ingest', data=data,
            headers={'Content-Type': 'application/json', 'OAI-Sites-Authorization': 'Bearer ' + token})
        try:
            with opener.open(request, timeout=45) as response:
                if 200 <= response.status < 300:
                    return
        except urllib.error.HTTPError as error:
            # Do not print response bodies, request headers or tokens.
            if error.code not in (408, 429, 500, 502, 503, 504):
                raise RuntimeError(f'MCP bridge rejected the relay (HTTP {error.code})') from None
        except urllib.error.URLError:
            pass
    raise RuntimeError('MCP delivery exhausted bounded retries; rerun this job after fixing the bridge/subscription')

def main():
    if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
        raise RuntimeError('This relay is scoped to ' + REPOSITORY)
    endpoint = os.environ.get('MCP_EVENTS_URL', '').rstrip('/')
    token = os.environ.get('MCP_EVENTS_SITE_TOKEN', '')
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme != 'https' or parsed.hostname != 'mac-mouse-fix-mcp-events.candidmars19.chatgpt.site' or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port:
        raise RuntimeError('Set MCP_EVENTS_URL to the exact private Site origin documented in SETUP.md')
    if not token:
        raise RuntimeError('Set repository secret MCP_EVENTS_SITE_TOKEN; never put its value in source or logs')
    payload = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    name = os.environ['GITHUB_EVENT_NAME']
    emitted = 0
    for pr in candidates(name, payload):
        event = event_for(name, payload, pr, os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT'])
        if event:
            deliver(event, endpoint, token)
            emitted += 1
            print(f'Delivered {event["eventId"]} for upstream-sync PR #{pr["number"]}')
    print(f'MCP Events relay complete: {emitted} matching event(s)')

if __name__ == '__main__':
    main()
