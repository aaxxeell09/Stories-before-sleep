import base64
import copy
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from openai import AsyncOpenAI
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('story_gen', ROOT / 'illustrated_story.py')
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def book_fixture():
    pages = []
    for number in (1, 2):
        pages.append({'page_number': number, 'image_description': 'Bear waves.',
            'narration': None if number == 1 else 'The moon shone.',
            'dialogue': [{'speaker': 'Bear', 'text': 'Hello, moon!', 'emotion': 'happy'}],
            'story_moment': 'context',
            'image_generation_payload': {
                'characters': [{'name': 'Bear', 'visual_description': 'Small brown bear',
                    'reference_image': None, 'emotion_on_page': 'happy', 'action_on_page': 'waving'}],
                'visual_continuity': {'location': 'Forest', 'important_objects': [],
                    'previous_page_context': None, 'persistent_environment_details': []},
                'style': {'emotional_tone': 'gentle'},
                'composition': {'primary_focus': 'Bear'}}})
    return {'story': {'title': 'Bear', 'full_story_text': 'Hello, moon! The moon shone. Hello, moon!',
                     'what_we_learned': 'Be kind.', 'try_it_today': 'Say hello.'},
            'visual_bible': {'illustration_style': 'Watercolor'}, 'pages': pages}


def image_result(size=(1536, 960)):
    data = io.BytesIO()
    Image.new('RGB', size, 'blue').save(data, format='PNG')
    return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(data.getvalue()).decode())])


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_reference_upload_and_response_decoding(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={'created': 1, 'data': [
                {'b64_json': image_result().data[0].b64_json}]})

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            reference = output / 'bear.png'
            Image.new('RGB', (64, 64), 'brown').save(reference)
            book = book_fixture()
            for page in book['pages']:
                page['image_generation_payload']['characters'][0]['reference_image'] = 'bear-ref'
            async with AsyncOpenAI(api_key='test-key', max_retries=0,
                    http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))) as client:
                await pipeline.generate_images(client, book, output, {'bear-ref': reference})
            self.assertEqual(len(requests), 2)
            for request in requests:
                self.assertEqual(request.url.path, '/v1/images/edits')
                self.assertIn(b'1536x960', request.content)
                self.assertIn(b'filename="bear.png"', request.content)
            self.assertIn(b'filename="page-001-native.png"', requests[1].content)

    async def test_story_query_and_session_cleanup(self):
        client = SimpleNamespace(use=AsyncMock(return_value={'token': 'session'}),
            chat=AsyncMock(return_value={'answers': [json.dumps(book_fixture())]}), terminate=AsyncMock())
        request = json.loads((ROOT / 'examples/story-request.json').read_text())
        prompt = pipeline.make_story_prompt(request)
        book = await pipeline.generate_story(client, prompt)
        self.assertEqual(len(pipeline.validate_book(book)), 2)
        question = client.chat.call_args.kwargs['question']
        self.assertTrue(question.expectJson)
        self.assertEqual(json.loads(question.questions[0].text)['child']['age'], 3)
        client.terminate.assert_awaited_once_with('session')

    async def test_invalid_story_terminates_session(self):
        client = SimpleNamespace(use=AsyncMock(return_value={'token': 'session'}),
            chat=AsyncMock(return_value={'answers': ['{"pages":']}), terminate=AsyncMock())
        with self.assertRaisesRegex(ValueError, 'invalid or truncated'):
            await pipeline.generate_story(client, {})
        client.terminate.assert_awaited_once()

    async def test_generate_retrieve_resize_and_resume(self):
        client = SimpleNamespace(images=SimpleNamespace(
            generate=AsyncMock(return_value=image_result()), edit=AsyncMock(return_value=image_result())))
        book = book_fixture()
        original = copy.deepcopy(book)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = await pipeline.generate_images(client, book, output, {})
            self.assertEqual(result['status'], 'complete')
            self.assertEqual([p['page_number'] for p in result['pages']], [1, 2])
            client.images.generate.assert_awaited_once()
            client.images.edit.assert_awaited_once()
            self.assertEqual(len(client.images.edit.call_args.kwargs['image']), 1)
            for page in result['pages']:
                with Image.open(output / page['image']) as image:
                    self.assertEqual(image.size, (1440, 900))
                with Image.open(output / page['native_image']) as image:
                    self.assertEqual(image.size, (1536, 960))
            prompt = json.loads((output / 'image-queries/page-001.json').read_text())
            self.assertIsNone(prompt['page']['narration'])
            self.assertEqual(prompt['page']['dialogue'][0]['text'], 'Hello, moon!')
            self.assertEqual(prompt['image_output']['height_px'], 960)
            (output / 'images/page-002.png').unlink()
            await pipeline.generate_images(client, book, output, {})
            self.assertTrue((output / 'images/page-002.png').exists())
            client.images.generate.assert_awaited_once()
            client.images.edit.assert_awaited_once()
        self.assertEqual(book, original)

    async def test_failure_keeps_completed_page_and_resumes(self):
        client = SimpleNamespace(images=SimpleNamespace(generate=AsyncMock(return_value=image_result()),
                                                        edit=AsyncMock(side_effect=RuntimeError('API unavailable'))))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.assertRaises(RuntimeError):
                await pipeline.generate_images(client, book_fixture(), output, {})
            manifest = json.loads((output / 'manifest.json').read_text())
            self.assertEqual(manifest['failed_page'], 2)
            self.assertEqual(len(manifest['pages']), 1)
            client.images.edit.side_effect = None
            client.images.edit.return_value = image_result()
            result = await pipeline.generate_images(client, book_fixture(), output, {})
            self.assertEqual(result['status'], 'complete')
            client.images.generate.assert_awaited_once()

    async def test_rejects_wrong_dimensions_and_unknown_reference(self):
        client = SimpleNamespace(images=SimpleNamespace(generate=AsyncMock(return_value=image_result((1024, 1024)))))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.assertRaisesRegex(ValueError, 'Expected a 1536x960'):
                await pipeline.generate_images(client, book_fixture(), output, {})
            self.assertFalse((output / 'images/page-001.png').exists())
            book = book_fixture()
            book['pages'][0]['image_generation_payload']['characters'][0]['reference_image'] = '/etc/passwd'
            with self.assertRaisesRegex(ValueError, 'No reference file'):
                await pipeline.generate_images(client, book, output, {})
            client.images.generate.assert_awaited_once()

    def test_rejects_out_of_order_pages(self):
        book = book_fixture()
        book['pages'].reverse()
        with self.assertRaisesRegex(ValueError, 'sequentially'):
            pipeline.validate_book(book)


class WebWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_ui_inputs_reach_illustrated_runner(self):
        import web_worker
        from unittest.mock import patch
        seen = {}

        async def generate(args):
            seen.update(json.loads(args.request.read_text()))
            self.assertFalse(args.resume)
            args.output.mkdir()

        with tempfile.TemporaryDirectory() as directory:
            with patch('web_worker.LOCAL_BOOKS', Path(directory)), patch('web_worker.load') as loader, patch('illustrated_story.run', side_effect=generate):
                loader.return_value.save_child_age.return_value = 3
                result = await web_worker.run(dict(kind='generate', age=3, minutes=5, rhyme=True,
                                                   lesson='Share', characters='Sea turtles', illustrated=True))
        self.assertTrue(result['book_id'])
        self.assertEqual(seen['child']['age'], 3)
        self.assertEqual(seen['preferences']['read_time_minutes'], 5)
        self.assertTrue(seen['preferences']['rhyming'])
        self.assertIn('Sea turtles', seen['child']['interests'])
        self.assertEqual(seen['lesson'], 'Share')


if __name__ == '__main__':
    unittest.main()
