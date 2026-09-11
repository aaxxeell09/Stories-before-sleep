"""Read only public story fields and final page images from local book folders."""
import hashlib
import json
from pathlib import Path

LOCAL_BOOKS = Path(__file__).resolve().parent / 'data' / 'books'


def book_id(folder):
    return hashlib.sha256(str(folder.resolve()).encode()).hexdigest()[:24]


class BookShelf:
    def __init__(self, roots=()):
        self.roots = [LOCAL_BOOKS.resolve(), *(Path(root).resolve() for root in roots)]

    def folders(self):
        folders = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            for folder in (root, *root.iterdir()):
                if folder.is_dir() and folder.resolve().is_relative_to(root) and (folder / 'storybook.json').is_file():
                    folders[book_id(folder)] = folder.resolve()
        return folders

    @staticmethod
    def file(folder, relative):
        if not isinstance(relative, str):
            raise ValueError('Invalid book file')
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder) or not path.is_file():
            raise ValueError('Book file is missing or outside the book folder')
        return path

    def read(self, identifier):
        folder = self.folders().get(identifier)
        if folder is None:
            raise ValueError('Book not found')
        book = json.loads(self.file(folder, 'storybook.json').read_text())
        manifest = {'status': 'generating', 'pages': []}
        if (folder / 'manifest.json').exists():
            manifest = json.loads(self.file(folder, 'manifest.json').read_text())
        images = {page['page_number']: page for page in manifest['pages']}
        pages = []
        for number, page in enumerate(book['pages'], 1):
            if page['page_number'] != number:
                raise ValueError('Book pages are not in order')
            image = None
            if number in images:
                try:
                    path = self.file(folder, images[number]['image'])
                    if path.suffix.lower() == '.png':
                        image = f'/api/books/{identifier}/images/{number}'
                except (ValueError, OSError):
                    pass
            pages.append({'page_number': number, 'image': image,
                          'narration': page.get('narration'), 'dialogue': page.get('dialogue', []),
                          'image_description': page.get('image_description', '')})
        story = book['story']
        return {'id': identifier, 'title': story['title'], 'story': story['full_story_text'],
                'what_we_learned': story['what_we_learned'], 'try_it_today': story.get('try_it_today', ''),
                'status': manifest['status'], 'pages': pages}

    def list(self):
        books = []
        for identifier in self.folders():
            try:
                book = self.read(identifier)
                books.append({key: book[key] for key in ('id', 'title', 'status')})
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return books

    def image(self, identifier, number):
        folder = self.folders().get(identifier)
        if folder is None:
            raise ValueError('Book not found')
        manifest = json.loads(self.file(folder, 'manifest.json').read_text())
        for page in manifest['pages']:
            if page['page_number'] == number:
                path = self.file(folder, page['image'])
                if path.suffix.lower() == '.png':
                    return path
        raise ValueError('Page image not found')
