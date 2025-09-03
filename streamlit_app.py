import os
import streamlit as st
import tempfile
import pandas as pd

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain.tools.retriever import create_retriever_tool
from langchain_experimental.utilities import PythonREPL
from langchain_experimental.tools import PythonREPLTool
from langchain.prompts import ChatPromptTemplate
from langchain.agents import create_tool_calling_agent, AgentExecutor


# --------------------------------------------------------------------
# 1. Web Search Tool
# --------------------------------------------------------------------
def search_web():
    return TavilySearchResults(k=6, name="web_search")


# --------------------------------------------------------------------
# 2. PDF Tool
# --------------------------------------------------------------------
def load_pdf_files(uploaded_files):
    all_documents = []
    for uploaded_file in uploaded_files:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.read())
            tmp_file_path = tmp_file.name

        loader = PyPDFLoader(tmp_file_path)
        documents = loader.load()
        all_documents.extend(documents)

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    split_docs = text_splitter.split_documents(all_documents)

    vector = FAISS.from_documents(split_docs, OpenAIEmbeddings())
    retriever = vector.as_retriever()

    retriever_tool = create_retriever_tool(
        retriever,
        name="pdf_search",
        description="Search for information from the uploaded PDF files"
    )
    return retriever_tool


# --------------------------------------------------------------------
# 3. CSV (Python REPL) Tool
# --------------------------------------------------------------------
def load_csv_tool(csv_file):
    df = pd.read_csv(csv_file)
    custom_repl = PythonREPL()
    custom_repl.globals["df"] = df

    repl_tool = PythonREPLTool(
        python_repl=custom_repl,
        name="csv_repl",
        description="Execute Python code to inspect and analyze the CSV data. DataFrame is available as variable `df`."
    )
    return repl_tool


# --------------------------------------------------------------------
# 4. Agent + Prompt 구성
# --------------------------------------------------------------------
def build_agent(tools):
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a helpful assistant for KEPCO KDN employees. "
         "If the question mentions '데이터', always call `csv_repl`. "
         "If the answer is in the PDF, call `pdf_search`. "
         "Otherwise, call `web_search`. "
         "When using csv_repl, always execute Python code on the DataFrame `df` "
         "and return the exact execution result in Korean."),
        ("placeholder", "{chat_history}"),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}")
    ])

    agent = create_tool_calling_agent(llm=llm, tools=tools, prompt=prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, return_intermediate_steps=True)
    return agent_executor


# --------------------------------------------------------------------
# 5. Agent 실행 함수
# --------------------------------------------------------------------
def ask_agent(agent_executor, question: str):
    result = agent_executor.invoke({"input": question})
    answer = result["output"]

    used_tools = []
    for step in result.get("intermediate_steps", []):
        tool_name = step[0].tool
        obs = step[1]

        if tool_name == "csv_repl":
            used_tools.append(tool_name)
        else:
            if obs and len(str(obs).strip()) > 30:
                used_tools.append(tool_name)

    used_tools = list(set(used_tools))
    return f" 답변:\n{answer}\n\n 사용된 툴: {', '.join(used_tools) if used_tools else '없음'}"


# --------------------------------------------------------------------
# 6. Streamlit 메인
# --------------------------------------------------------------------
def main():
    st.set_page_config(page_title="한전KDN AI 비서", layout="wide", page_icon="🤖")
    st.image('data/kdn_image.jpg', width=800)
    st.markdown('---')
    st.title("안녕하세요! RAG + Web + CSV를 활용한 '한전KDN AI 비서' 입니다")  

    with st.sidebar:
        openai_api = st.text_input("OPENAI API 키", type="password")
        tavily_api = st.text_input("TAVILY API 키", type="password")
        pdf_docs = st.file_uploader("PDF 파일 업로드", accept_multiple_files=True)
        csv_file = st.file_uploader("CSV 파일 업로드", type="csv")

    if openai_api and tavily_api:
        os.environ['OPENAI_API_KEY'] = openai_api
        os.environ['TAVILY_API_KEY'] = tavily_api

        tools = [search_web()]
        if pdf_docs:
            tools.append(load_pdf_files(pdf_docs))
        if csv_file:
            tools.append(load_csv_tool(csv_file))

        agent_executor = build_agent(tools)

        if "messages" not in st.session_state:
            st.session_state["messages"] = []

        user_input = st.chat_input("질문을 입력하세요")

        if user_input:
            response = ask_agent(agent_executor, user_input)
            st.session_state["messages"].append({"role": "user", "content": user_input})
            st.session_state["messages"].append({"role": "assistant", "content": response})

        for msg in st.session_state["messages"]:
            st.chat_message(msg["role"]).write(msg["content"])

    else:
        st.warning("API 키를 입력하세요.")


if __name__ == "__main__":
    main()
