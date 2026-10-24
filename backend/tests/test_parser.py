from app.parsers.code_parser import parse_code

def test_python_symbols_and_lines():
    chunks=parse_code('import os\n\nclass Demo:\n    def hello(self):\n        return "hi"\n','python')
    assert any(c.symbol=='Demo' for c in chunks)
    assert any('hello' in c.content for c in chunks)

def test_fallback_chunking():
    chunks=parse_code('one\ntwo\nthree\n','python')
    assert chunks[0].start_line==1
