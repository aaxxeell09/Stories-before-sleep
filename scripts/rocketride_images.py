"""Generate images via RocketRide's HTTP tool; never call OpenAI locally."""

import base64
import re
from types import SimpleNamespace

from PIL import Image


class ImageRequestError(RuntimeError):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        super().__init__(
            f"OpenAI image request through RocketRide failed (HTTP {diagnostic['http_status']}; "
            f"code={diagnostic['code']}): {diagnostic['message']}")


class RocketRideImages:
    def __init__(self, client, token, api_key):
        self.client = client
        self.token = token
        self.api_key = api_key
        self.images = self

    async def generate(self, **kwargs):
        return await self._request([], **kwargs)

    async def edit(self, *, image, **kwargs):
        content = []
        for file in image:
            data = file.read()
            file.seek(0)
            with Image.open(file) as parsed:
                mime = Image.MIME[parsed.format]
            content.append({'type': 'input_image',
                            'image_url': f'data:{mime};base64,' + base64.b64encode(data).decode()})
        return await self._request(content, **kwargs)

    async def _request(self, content, *, model, prompt, size, quality, output_format, n):
        if n != 1:
            raise ValueError('Only one image per page request is supported')
        body = {
            'model': 'gpt-4.1',
            'store': False,
            'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': prompt}] + content}],
            'tools': [{'type': 'image_generation', 'model': model, 'size': size,
                       'quality': quality, 'output_format': output_format}],
            'tool_choice': {'type': 'image_generation'},
            'parallel_tool_calls': False,
        }
        url = 'https://api.openai.com/v1/responses'
        if not content:
            url = 'https://api.openai.com/v1/images/generations'
            body = dict(model=model, prompt=prompt, size=size, quality=quality,
                        output_format=output_format, n=n)
        response = await self.client.tool(
            token=self.token, node_id='openai_images', tool='http_request', timeout=360_000,
            input={'url': url, 'method': 'POST',
                   'bearer_token': self.api_key, 'body_json': body, 'timeout': 300})
        if not isinstance(response, dict) or response.get('status_code') != 200:
            status = response.get('status_code', 'unknown') if isinstance(response, dict) else 'unknown'
            # Preserve actionable provider diagnostics, never the request or credentials.
            payload = response.get('json') if isinstance(response, dict) else None
            error = payload.get('error') if isinstance(payload, dict) else None
            error = error if isinstance(error, dict) else {}
            def clean(value):
                text = str(value or '')
                if self.api_key:
                    text = text.replace(self.api_key, '[redacted]')
                return re.sub(r'sk-[A-Za-z0-9_-]+', '[redacted]', text)[:2000]
            headers = response.get('headers') if isinstance(response, dict) else None
            headers = {k.lower(): v for k, v in headers.items()} if isinstance(headers, dict) else {}
            raise ImageRequestError({
                'http_status': status, 'code': clean(error.get('code')),
                'message': clean(error.get('message')) or 'No error details returned',
                'request_id': clean(headers.get('x-request-id')),
            })
        payload = response.get('json')
        if not content:
            data = payload.get('data', []) if isinstance(payload, dict) else []
            if len(data) != 1 or not data[0].get('b64_json'):
                raise RuntimeError('Expected one base64 image from RocketRide')
            return SimpleNamespace(data=[SimpleNamespace(b64_json=data[0]['b64_json'])])
        if not isinstance(payload, dict) or payload.get('status') != 'completed':
            raise RuntimeError('OpenAI image response did not complete')
        calls = [item for item in payload.get('output', []) if item.get('type') == 'image_generation_call']
        if len(calls) != 1 or not calls[0].get('result'):
            raise RuntimeError('Expected one image from RocketRide; none or multiple returned')
        return SimpleNamespace(data=[SimpleNamespace(b64_json=calls[0]['result'])])
