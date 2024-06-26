from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_community.embeddings.sentence_transformer import SentenceTransformerEmbeddings
from langchain_text_splitters import MarkdownHeaderTextSplitter
from langchain.schema import Document
from finrobot.data_source.earnings_calls_src import get_earnings_all_docs
from finrobot.data_source.filings_src import sec_main as unstructured_sec_main
from finrobot.data_source.marker_sec_src.sec_filings_to_pdf import sec_save_pdfs
from finrobot.data_source.marker_sec_src.pdf_to_md import run_marker as run_marker_single
from finrobot.data_source.marker_sec_src.pdf_to_md_parallel import run_marker_mp
from finrobot.data_source.finance_data import get_data
from typing import List, Optional
import os
SAVE_DIR = "output/SEC_EDGAR_FILINGS_MD"


def rag_database_earnings_call(
        ticker: str,
        year: str)->str:
        
        #assert quarter in earnings_call_quarter_vals, "The quarter should be from Q1, Q2, Q3, Q4"
        earnings_docs, earnings_call_quarter_vals, speakers_list_1, speakers_list_2, speakers_list_3, speakers_list_4 = get_data(ticker=ticker,year=year,data_source='earnings_calls')

        emb_fn = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")

        text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1024,
        chunk_overlap=100,
        length_function=len,)
        earnings_calls_split_docs = text_splitter.split_documents(earnings_docs)

        earnings_call_db = Chroma.from_documents(earnings_calls_split_docs, emb_fn, persist_directory="./earnings-call-db",collection_name="earnings_call")


        quarter_speaker_dict = {
        "Q1":speakers_list_1,
        "Q2":speakers_list_2,
        "Q3":speakers_list_3,
        "Q4":speakers_list_4}
    
        def query_database_earnings_call(
        question: str,
        quarter: str)->str:
            """This tool will query the earnings call transcripts database for a given question and quarter and it will retrieve
            the relevant text along from the earnings call and the speaker who addressed the relevant documents. This tool helps in answering questions
            from the earnings call transcripts.

            Args:
            question (str): _description_. Question to query the database for relevant documents.
            quarter (str): _description_. the financial quarter that is discussed in the question and possible options are Q1, Q2, Q3, Q4

            Returns:
            str: relevant text along from the earnings call and the speaker who addressed the relevant documents
            """
            assert quarter in earnings_call_quarter_vals, "The quarter should be from Q1, Q2, Q3, Q4"

            req_speaker_list = []
            quarter_speaker_list = quarter_speaker_dict[quarter]

            for sl in quarter_speaker_list:
                if sl in question or sl.lower() in question:
                    req_speaker_list.append(sl)
            if len(req_speaker_list) == 0:
                req_speaker_list = quarter_speaker_list

            relevant_docs = earnings_call_db.similarity_search(
            question,
            k=5,
            filter={
                "$and":[
                    {
                        "quarter":{"$eq":quarter}
                    },
                    {
                        "speaker":{"$in":req_speaker_list}
                    }
                ]
            }
        )

            speaker_releavnt_dict = {}
            for doc in relevant_docs:
                speaker = doc.metadata['speaker']
                speaker_text = doc.page_content
                if speaker not in speaker_releavnt_dict:
                    speaker_releavnt_dict[speaker] = speaker_text
                else:
                    speaker_releavnt_dict[speaker] += " "+speaker_text

            relevant_speaker_text = ""
            for speaker, text in speaker_releavnt_dict.items():
                relevant_speaker_text += speaker + ": "
                relevant_speaker_text += text + "\n\n"

            return relevant_speaker_text

        return query_database_earnings_call, earnings_call_quarter_vals, quarter_speaker_dict







def rag_database_sec(
        ticker: str,
        year: str,
        FROM_MARKDOWN = False,
        filing_types = ['10-K','10-Q'])->str:
    if not FROM_MARKDOWN:
        sec_data,sec_form_names = get_data(ticker=ticker, year=year,data_source='unstructured',include_amends=True,filing_types=filing_types)
        emb_fn = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")
        text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1024,
        chunk_overlap=100,
        length_function=len,)
        sec_filings_split_docs = text_splitter.split_documents(sec_data)

        sec_filings_unstructured_db = Chroma.from_documents(sec_filings_split_docs, emb_fn, persist_directory="./sec-filings-db",collection_name="sec_filings")
    
        def query_database_unstructured_sec(question: str,sec_form_name: str)->str:
            """This tool will query the SEC Filings database for a given question and form name, and it will retrieve
            the relevant text along from the SEC filings and the section names. This tool helps in answering questions
            from the sec filings.

            Args:
            question (str): _description_. Question to query the database for relevant documents
            sec_form_name (str): _description_. SEC FORM NAME that the question is talking about. It can be 10-K for yearly data and 10-Q for quarterly data. For quarterly data, it can be 10-Q2 to represent Quarter 2 and similarly for other quarters.
            
           

            Returns:
            str: Relevant context for the question from the sec filings
            """
            relevant_docs = sec_filings_unstructured_db.similarity_search(
            question,
            k=5,
            filter={
            "form_name":{"$eq":sec_form_name}
            }
        )
            relevant_section_dict = {}
            for doc in relevant_docs:
                section = doc.metadata['section_name']
                section_text = doc.page_content
                if section not in relevant_section_dict:
                    relevant_section_dict[section] = section_text
                else:
                    relevant_section_dict[section] += " "+section_text

            relevant_section_text = ""
            for section, text in relevant_section_dict.items():
                relevant_section_text += section + ": "
                relevant_section_text += text + "\n\n"
            return relevant_section_text

        return query_database_unstructured_sec, sec_form_names
    
    elif FROM_MARKDOWN:
        sec_data,sec_form_names = get_data(ticker=ticker, year=year,data_source='unstructured',include_amends=True,filing_types=filing_types)
        get_data(ticker=ticker,year=year,data_source='marker_pdf',batch_processing=False,batch_multiplier=1)

        headers_to_split_on = [
        ("#", "Header 1"),
        ("##", "Header 2"),
        ("###", "Header 3"),
        ]
        markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
        markdown_dir = "output/SEC_EDGAR_FILINGS_MD"
        md_content_list = []
        for md_dirs in os.listdir(os.path.join(markdown_dir,f"{ticker}-{year}")):
            md_file_path = os.path.join(markdown_dir,f"{ticker}-{year}",md_dirs,f"{md_dirs}.md")
            with open(md_file_path, 'r') as file:
                content = file.read()
            md_content_list.append([content,'-'.join(md_dirs.split('-')[-2:])])
        
        sec_markdown_docs = []

        for md_content in md_content_list:
            md_header_splits = markdown_splitter.split_text(md_content[0])
            for md_header_docs in md_header_splits:
                md_header_docs.metadata.update({"filing_type":md_content[1]})
            sec_markdown_docs.extend(md_header_splits)

        sec_filings_md_db = Chroma.from_documents(sec_markdown_docs, emb_fn, persist_directory="./sec-filings-md-db",collection_name="sec_filings_md")

        def query_database_markdown_sec(
            question: str,
            sec_form_name: str)->str:
            """This tool will query the SEC Filings database for a given question and form name, and it will retrieve
            the relevant text along from the SEC filings and the section names. This tool helps in answering questions
            from the sec filings.

            Args:
            question (str): _description_. Question to query the database for relevant documents
            sec_form_name (str): _description_. SEC FORM NAME that the question is talking about. It can be 10-K for yearly data and 10-Q for quarterly data. For quarterly data, it can be 10-Q2 to represent Quarter 2 and similarly for other quarters.
            
           

            Returns:
            str: Relevant context for the question from the sec filings
            """
            assert sec_form_name in sec_form_names, f'The search form type should be in {sec_form_names}'

            relevant_docs = sec_filings_md_db.similarity_search(
            question,
            k=3,
            filter={
            "filing_type":{"$eq":sec_form_name}
            }
            )
   
            relevant_section_text = ""
            for relevant_text in relevant_docs:
                relevant_section_text += relevant_text.page_content + "\n\n"

            return relevant_section_text
        return query_database_markdown_sec, sec_form_names
