import importlib.util
from pathlib import Path
import unittest
import urllib.error

spec = importlib.util.spec_from_file_location('relay', Path(__file__).parents[1] / 'relay/relay.py')
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)

def pr(number=3):
    return {'number': number, 'state': 'open', 'draft': False, 'title': 'Review upstream updates',
            'updated_at': '2026-10-29T10:00:00Z',
            'head': {'ref': relay.BRANCH, 'sha': 'a'*40, 'repo': {'full_name': relay.REPOSITORY}},
            'base': {'ref': 'master', 'sha': 'b'*40, 'repo': {'full_name': relay.REPOSITORY}}}

class RelayTests(unittest.TestCase):
    def test_bootstrap_three_and_future(self):
        for n in [3, 18]:
            self.assertEqual(relay.event_for('workflow_dispatch', {}, pr(n), '100', '1')['data']['pull_request_number'], n)

    def test_foreign_closed_draft_and_unrelated_rejected(self):
        for field, value in [('state', 'closed'), ('draft', True)]:
            p=pr();p[field]=value;self.assertIsNone(relay.event_for('workflow_dispatch',{},p,'100','1'))
        p=pr();p['head']['ref']='other';self.assertIsNone(relay.event_for('workflow_dispatch',{},p,'100','1'))
        p=pr();p['head']['repo']['full_name']='evil/fork';self.assertIsNone(relay.event_for('workflow_dispatch',{},p,'100','1'))

    def test_workflow_run_finds_bot_created_pr(self):
        paths=[]
        def get(path): paths.append(path);return [pr()]
        payload={'workflow_run': {'name':'Sync upstream','head_branch':'master','head_repository':{'full_name':relay.REPOSITORY}}}
        self.assertEqual(len(relay.candidates('workflow_run',payload,get)),1)
        self.assertIn('state=open',paths[0])
        payload['workflow_run']['head_branch']='untrusted'
        self.assertEqual(relay.candidates('workflow_run',payload,get),[])

    def test_human_feedback_only_and_issue_not_pr_ignored(self):
        payload={'issue':{'number':3,'pull_request':{}},'comment':{'user':{'type':'Bot','login':'bot[bot]'}}}
        self.assertEqual(relay.candidates('issue_comment',payload,lambda _:pr()),[])
        payload['issue']['pull_request']={'url':'a'};payload['comment']['user']={'type':'User','login':'reviewer'}
        self.assertEqual(len(relay.candidates('issue_comment',payload,lambda _:pr())),1)

    def test_agent_commit_does_not_feedback_loop(self):
        e=relay.event_for('pull_request_target',{'action':'synchronize'},pr(),'100','1',lambda _:{'commit':{'message':'[mcp-upstream] Resolve conflict'}})
        self.assertIsNone(e)
        e=relay.event_for('pull_request_target',{'action':'synchronize'},pr(),'100','1',lambda _:{'commit':{'message':'External update'}})
        self.assertEqual(e['data']['reason'],'pr_updated')

    def test_retry_identity_and_occurrence_timestamp(self):
        a=relay.event_for('workflow_dispatch',{},pr(),'100','1')
        self.assertEqual(a,relay.event_for('workflow_dispatch',{},pr(),'100','1'))
        self.assertNotEqual(a['eventId'],relay.event_for('workflow_dispatch',{},pr(),'100','2')['eventId'])
        self.assertEqual(a['timestamp'],pr()['updated_at'])

    def test_event_has_no_raw_comment_body(self):
        e=relay.event_for('issue_comment',{'comment':{'id':1,'body':'untrusted instructions'}},pr(),'100','1')
        self.assertNotIn('body',e['data'])

    def test_transient_retry_uses_same_bytes_and_does_not_follow_redirect(self):
        class Result:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
        class Opener:
            requests=[]
            def open(self,r,timeout):
                self.requests.append(r)
                if len(self.requests)==1:raise urllib.error.HTTPError(r.full_url,503,'bad',{},None)
                return Result()
        opener=Opener();delays=[]
        relay.deliver(relay.event_for('workflow_dispatch',{},pr(),'100','1'),'https://bridge.test','secret',opener,delays.append)
        self.assertEqual(opener.requests[0].data,opener.requests[1].data)
        self.assertEqual(delays,[2])

    def test_permanent_errors_do_not_retry(self):
        class Opener:
            def open(self,r,timeout):raise urllib.error.HTTPError(r.full_url,403,'bad',{},None)
        with self.assertRaisesRegex(RuntimeError,'HTTP 403'):
            relay.deliver({},'https://bridge.test','secret',Opener(),lambda _:self.fail('must not retry'))

if __name__ == '__main__':unittest.main()
