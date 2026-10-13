from app.parsers.code_parser import parse_code

def test_python_symbols_and_lines():
    chunks=parse_code('import os\n\nclass Demo:\n    def hello(self):\n        return "hi"\n','python')
    assert any(c.symbol=='Demo' for c in chunks)
    assert any('hello' in c.content for c in chunks)
    assert any(c.symbol=='hello' and c.symbol_type=='method' for c in chunks)

def test_fallback_chunking():
    chunks=parse_code('one\ntwo\nthree\n','python')
    assert chunks[0].start_line==1

def test_java_class_and_method_symbols():
    chunks=parse_code('public class Notify {\n  private KafkaProducer producer;\n  public void retry() {\n    send();\n  }\n}\n','java')
    assert any(c.symbol=='Notify' and c.symbol_type=='class' for c in chunks)
    assert any(c.symbol=='retry' and c.symbol_type=='method' and c.start_line==3 for c in chunks)
    assert any('KafkaProducer' in c.references for c in chunks)

def test_ast_chunks_are_bounded_and_keep_line_ranges():
    source='class Large:\n'+''.join(f'    value_{i} = "{"x"*80}"\n' for i in range(80))
    chunks=parse_code(source,'python')
    large_chunks=[chunk for chunk in chunks if chunk.symbol.startswith('Large')]
    assert len(large_chunks)>1
    assert all(len(chunk.content)<=1800 for chunk in large_chunks)
    assert all(chunk.start_line<=chunk.end_line for chunk in large_chunks)
