"""Tests for offline news, publishing permissions and the distribution workflow."""
import base64
import json
import tempfile
from pathlib import Path
from unittest import TestCase, mock
import unittest

import notices
import notices_admin


def mk_notice(ident='id_1', published=True, pinned=False):
    return {'id':ident, 'title':'重要なお知らせ', 'body':'ゲームの新しいお知らせです。\n配布ページも見られます。',
        'category':'update', 'pinned':pinned, 'published':published,
        'published_at':'2026-10-20', 'url':notices.LATEST_URL}


class TestNoticeModel(TestCase):
    def test_validate_japanese_unicode(self):
        data = {'schema':1,'notices':[mk_notice()]}
        raw = notices.encode_feed(data)
        self.assertIn('お知らせ'.encode('utf-8'), raw)
        self.assertEqual(notices.validate_feed(json.loads(raw))['notices'][0]['title'], '重要なお知らせ')

    def test_sorted_and_draft_hidden(self):
        feed={'schema':1,'notices':[mk_notice('draft',False),mk_notice('pin',pinned=True),mk_notice('regular')]}
        self.assertEqual([x['id'] for x in notices.public_view(feed)],['pin','regular'])
        self.assertEqual(notices.unread_count(feed,{'pin'}),1)

    def test_duplicates_and_urls_rejected(self):
        with self.assertRaises(ValueError):
            notices.validate_feed({'schema':1,'notices':[mk_notice(),mk_notice()]})
        hostile=mk_notice();hostile['url']='https://evil.example/collect'
        with self.assertRaises(ValueError):notices.validate_feed({'schema':1,'notices':[hostile]})

    def test_round_trip_and_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(notices,'profile_dir',return_value=Path(tmp)):
                feed={'schema':1,'notices':[mk_notice()]}
                notices.save_feed(notices.cached_path(),feed)
                self.assertEqual(notices.load_offline(),feed)
                self.assertEqual(notices.load_seen(),set())
                self.assertEqual(notices.mark_seen('id_1'),{'id_1'})
                self.assertEqual(notices.load_seen(),{'id_1'})

    def test_offline_missing_falls_back_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(notices,'profile_dir',return_value=Path(tmp)):
                result=notices.load_offline()
                self.assertTrue(result['notices'])

    def test_fetch_public_from_mocked_urlopen(self):
        feed={'schema':1,'notices':[mk_notice()]}
        class FakeResponse:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def geturl(self):return notices.FEED_URL
            def read(self, maxbytes):return notices.encode_feed(feed)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(notices,'urlopen',return_value=FakeResponse()), mock.patch.object(notices,'profile_dir',return_value=Path(tmp)):
                fetched=notices.fetch_public()
                self.assertEqual(fetched,feed)
                self.assertEqual(notices.read_feed(notices.cached_path()),feed)

    def test_redirect_is_blocked(self):
        class BadResponse:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def geturl(self):return 'https://evil.example/payload'
        with mock.patch.object(notices,'urlopen',return_value=BadResponse()):
            with self.assertRaises(ValueError):notices.fetch_public()


class TestPublishAndRelease(TestCase):
    def test_publish_only_public_not_drafts(self):
        feed={'schema':1,'notices':[mk_notice('pub'),mk_notice('private',published=False)]}
        captured={}
        def fake_gh(*args):
            if '--input' in args:
                filename=Path(args[args.index('--input')+1])
                doc=json.loads(filename.read_text('utf8'))
                captured['payload']=json.loads(base64.b64decode(doc['content']))
                captured['message']=doc['message']
            return '{}'
        with mock.patch.object(notices_admin,'get_remote_file',return_value=None),mock.patch.object(notices_admin,'run_gh',side_effect=fake_gh):
            notices_admin.publish_announcements(feed)
        self.assertEqual([n['id'] for n in captured['payload']['notices']],['pub'])

    def test_remote_sha_for_overwrite(self):
        feed={'schema':1,'notices':[mk_notice()]}
        captured={}
        def fake_gh(*args):
            filename=Path(args[args.index('--input')+1]); captured.update(json.loads(filename.read_text('utf8')))
            return '{}'
        with mock.patch.object(notices_admin,'get_remote_file',return_value={'sha':'abc123'}),mock.patch.object(notices_admin,'run_gh',side_effect=fake_gh):
            notices_admin.publish_announcements(feed)
        self.assertEqual(captured['sha'],'abc123')

    def test_release_requires_version_match(self):
        with mock.patch.object(notices_admin,'remote_version',return_value='0.6.1'):
            with self.assertRaises(ValueError):notices_admin.create_release('0.7.0','Release notes')

    def test_release_calls_gh_with_explicit_latest(self):
        calls=[]
        with mock.patch.object(notices_admin,'remote_version',return_value='0.7.0'), mock.patch.object(notices_admin,'run_gh',side_effect=lambda *a:calls.append(a)):
            notices_admin.create_release('0.7.0','新しい機能')
        self.assertIn('--latest',calls[0]);self.assertIn('v0.7.0',calls[0])

    def test_no_remote_auth_from_local_pass(self):
        with mock.patch.object(notices_admin,'run_gh',side_effect=RuntimeError('GH unavailable')):
            with self.assertRaises(RuntimeError):notices_admin.publish_announcements({'schema':1,'notices':[mk_notice()]})

if __name__=='__main__':unittest.main()
