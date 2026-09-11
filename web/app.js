const $ = (id) => document.getElementById(id);
let currentStory = '', activeView = 'story', settings;
const sample = 'The Little Shell Boat\n\nFinn the clownfish found a shiny shell. “A boat!” he said, pushing it through the water.\n\nSquid wanted a turn. Finn held the shell close. “But I just found it.”\n\nSquid waited quietly. The little boat did not feel quite as fun all alone.\n\n“You can sail it to the rock,” Finn said. “Then it’s my turn again.”\n\nSquid gave the shell a gentle push. Finn made tiny waves. Together, they sailed all the way home.\n\nWhat we learned\nTaking turns gives everyone a chance to have fun.';
function displayStory(text, label) { currentStory = text; $('story-result').textContent = text; $('story-result').hidden = false; $('empty').hidden = true; $('story-label').textContent = label; $('download').disabled = false; $('use-story').disabled = false; }
function showSetup() { if (!settings) return; const missing = activeView === 'story' ? settings.generation_missing : settings.memory_missing; $('setup').hidden = !missing.length; $('setup').textContent = `Setup needed: add ${missing.join(', ')} to .env, then refresh. You can read the example story while you set up.`; }
for (const view of ['story', 'memory']) $(view + '-tab').onclick = () => { activeView = view; for (const other of ['story', 'memory']) { $(other + '-view').hidden = other !== view; $(other + '-tab').classList.toggle('active', other === view); $(other + '-tab').setAttribute('aria-pressed', String(other === view)); } showSetup(); };
document.querySelectorAll('[data-lesson]').forEach(button => button.onclick = () => { $('lesson').value = button.dataset.lesson; });
$('sample').onclick = () => displayStory(sample, 'EXAMPLE STORY · NOT GENERATED');
$('use-story').onclick = () => { $('seed').value = currentStory; $('seed').focus(); };
$('download').onclick = () => { const url = URL.createObjectURL(new Blob([currentStory], {type: 'text/plain'})); const link = document.createElement('a'); link.href = url; link.download = 'storysprout-story.txt'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
async function api(url, options) { const response = await fetch(url, options); const body = await response.json(); if (!response.ok) throw new Error(body.error || 'Request failed.'); return body; }
async function submit(kind, payload) {
 const view = kind === 'generate' ? 'story' : 'memory', status = $(view + '-status');
 const buttons = document.querySelectorAll('button[type=submit]'); buttons.forEach(b => b.disabled = true);
 status.className = ''; status.textContent = kind === 'generate' ? (payload.illustrated ? 'Writing and illustrating your book… This can take several minutes. Finished pages are saved as they arrive.' : 'Writing your story… This may take a minute.') : 'Recalling, transferring, and verifying… This can take several minutes.';
 if (view === 'memory') $('memory-result').hidden = true;
 try {
  const job = await api('/api/jobs', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({kind, ...payload})});
  let result;
  for (;;) { await new Promise(resolve => setTimeout(resolve, 1500)); result = await api('/api/jobs/' + job.id); if (result.status !== 'running') break; }
  if (result.status === 'failed') throw new Error(result.error);
  if (kind === 'generate') { if (result.result.book_id) { await refreshBooks(); await openBook(result.result.book_id); } else { displayStory(result.result.story, 'TONIGHT’S STORY'); } status.textContent = 'Ready to read together.'; }
  else { $('memory-result').textContent = JSON.stringify(result.result.report, null, 2); $('memory-result').hidden = false; status.textContent = result.result.report.verified ? 'Verified: the lesson and supporting quote were independently retrieved from HydraDB.' : 'The transfer could not be verified.'; }
 } catch (error) { status.className = 'error'; status.textContent = error.message; }
 finally { buttons.forEach(b => b.disabled = false); }
}
$('story-form').onsubmit = event => { event.preventDefault(); submit('generate', {age:Number($('age').value), minutes:Number($('minutes').value), rhyme:$('rhyme').checked, illustrated:$('illustrated').checked, lesson:$('lesson').value, characters:$('characters').value}); };
$('memory-form').onsubmit = event => { event.preventDefault(); submit('memory', {dataset:$('dataset').value, query:$('query').value, story:$('seed').value}); };
api('/api/status').then(result => { settings = result; $('age').value = result.age; showSetup(); }).catch(() => { $('setup').hidden = false; $('setup').textContent = 'Cannot reach the local server. Restart web_app.py and refresh.'; });

async function refreshBooks() {
 const selected = $('saved-books').value;
 const {books} = await api('/api/books');
 $('saved-books').replaceChildren(new Option('Choose a book…', ''));
 for (const book of books) $('saved-books').add(new Option(`${book.title}${book.status === 'complete' ? '' : book.status === 'preview_complete' ? ' · preview' : book.status === 'failed' ? ' · images failed' : ' · generating'}`, book.id));
 $('saved-books').value = selected;
 $('books-status').textContent = books.length ? `${books.length} saved ${books.length === 1 ? 'book' : 'books'}.` : 'Your illustrated books will appear here after generation.';
}
function element(tag, text, className) { const node = document.createElement(tag); if (text) node.textContent = text; if (className) node.className = className; return node; }
async function openBook(id) {
 const book = await api('/api/books/' + encodeURIComponent(id));
 displayStory([book.title, book.story, 'What we learned', book.what_we_learned, book.try_it_today].filter(Boolean).join('\n\n'), 'ILLUSTRATED STORYBOOK');
 $('saved-books').value = id;
 const reader = $('story-result'); reader.replaceChildren(element('h2', book.title));
 if (book.status !== 'complete') {
  const progress = `${book.images_ready} of ${book.pages.length} illustrations available. `;
  const detail = book.status === 'failed' ? `${book.image_error}${book.failed_page ? ' Stopped at page ' + book.failed_page + '.' : ''}` : book.status === 'preview_complete' ? 'This preview run is finished. The remaining pages have not been illustrated.' : 'Generation is in progress. Refresh and reopen the book to load finished images.';
  reader.append(element('p', progress + detail, 'book-notice'));
 }
 for (const page of book.pages) {
  const section = element('section', null, 'book-page');
  section.append(element('p', `PAGE ${page.page_number} OF ${book.pages.length}`, 'page-number'));
  if (page.image) {
   const image = document.createElement('img'); image.src = page.image; image.alt = page.image_description || `Illustration for page ${page.page_number}`;
   image.width = 1440; image.height = 900; image.loading = 'lazy';
   image.onerror = () => { image.replaceWith(element('p', 'This page image is unavailable. The story text is below.', 'book-notice')); };
   section.append(image);
  } else section.append(element('p', book.status === 'failed' ? 'Illustration unavailable — generation stopped.' : book.status === 'preview_complete' ? 'Not illustrated in this preview.' : 'Illustration not available yet.', 'book-notice'));
  if (page.narration) section.append(element('p', page.narration, 'page-narration'));
  for (const line of page.dialogue) section.append(element('p', `${line.speaker}: “${line.text}”`, 'page-dialogue'));
  reader.append(section);
 }
 reader.append(element('h3', 'What we learned'), element('p', book.what_we_learned));
 if (book.try_it_today) reader.append(element('h3', 'Try it today'), element('p', book.try_it_today));
}
$('refresh-books').onclick = () => refreshBooks().catch(error => { $('books-status').textContent = error.message; });
$('saved-books').onchange = () => { if ($('saved-books').value) openBook($('saved-books').value).catch(error => { $('books-status').textContent = error.message; }); };
refreshBooks().catch(() => { $('books-status').textContent = 'Saved books are unavailable. Restart the server and refresh.'; });
