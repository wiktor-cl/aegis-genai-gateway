from aegis.agent.tools.knowledge_base import KnowledgeBaseSearchArgs, KnowledgeBaseSearchTool


async def test_finds_relevant_document_by_keyword() -> None:
    tool = KnowledgeBaseSearchTool()
    results = await tool.run(KnowledgeBaseSearchArgs(query="confidential data classification"))
    assert results
    assert results[0]["id"] == "kb-001"


async def test_respects_top_k() -> None:
    tool = KnowledgeBaseSearchTool()
    results = await tool.run(KnowledgeBaseSearchArgs(query="provider budget policy role", top_k=2))
    assert len(results) <= 2


async def test_no_match_returns_empty_list() -> None:
    tool = KnowledgeBaseSearchTool()
    results = await tool.run(KnowledgeBaseSearchArgs(query="xyzxyzxyz nonexistent"))
    assert results == []
