# Tests

The grouping, editor, cache-invalidation and streaming tests use an in-memory
MongoDB mock and test-only configuration. They check signed inline/range headers,
thumbnail revisions, partial failures, and preservation of post/profile data;
they do not connect to Telegram or require a running MongoDB server. Actual media
playback still depends on Telegram access and browser-supported codecs.

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r tests/requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```
