import os

os.environ["IN_STREAMLIT"] = "true"  # Avoid multiprocessing inside surya
os.environ["PDFTEXT_CPU_WORKERS"] = "1"  # Avoid multiprocessing inside pdftext
SAVE_DIR = "output/SEC_EDGAR_FILINGS_MD"

import pypdfium2  # Needs to be at the top to avoid warnings
from typing import Optional
import torch.multiprocessing as mp
from tqdm import tqdm
import math

from marker.convert import convert_single_pdf
from marker.output import markdown_exists, save_markdown
from marker.pdf.utils import find_filetype
from marker.pdf.extract_text import get_length_of_text
from marker.models import load_all_models
from marker.settings import settings
from marker.logger import configure_logging
import traceback
import json

configure_logging()
SAVE_DIR = "output/SEC_EDGAR_FILINGS_MD"

def worker_init(shared_model):
    global model_refs
    model_refs = shared_model


def worker_exit():
    global model_refs
    del model_refs


def process_single_pdf(args):
    filepath, out_folder, metadata, min_length = args

    fname = os.path.basename(filepath)
    if markdown_exists(out_folder, fname):
        return
    if not filepath.endswith("pdf"): 
        return
    try:
        # Skip trying to convert files that don't have a lot of embedded text
        # This can indicate that they were scanned, and not OCRed properly
        # Usually these files are not recent/high-quality
        if min_length:
            filetype = find_filetype(filepath)
            if filetype == "other":
                return 0

            length = get_length_of_text(filepath)
            if length < min_length:
                return
        
        full_text, images, out_metadata = convert_single_pdf(
            filepath, model_refs, metadata=metadata
        )
        if len(full_text.strip()) > 0:
            save_markdown(out_folder, fname, full_text, images, out_metadata)
        else:
            print(f"Empty file: {filepath}.  Could not convert.")
    except Exception as e:
        print(f"Error converting {filepath}: {e}")
        print(traceback.format_exc())


def run_marker_mp(
    in_folder,
    out_folder,
    chunk_idx=0,
    num_chunks=1,
    max_files=None,
    workers=5,
    metadata_file=None,
    min_length=None,
    inference_ram: Optional[int] = None,
    vram_per_task: Optional[int] = None,
):
    """
    Convert multiple PDFs to markdown using the provided parameters.

    Parameters:
    - in_folder: str
        Input folder containing PDF files.
    - out_folder: str
        Output folder where markdown files will be saved.
    - chunk_idx: int, optional
        Chunk index to convert. Default is 0.
    - num_chunks: int, optional
        Number of chunks being processed in parallel. Default is 1.
    - max_files: int, optional
        Maximum number of PDFs to convert. Default is None (no limit).
    - workers: int, optional
        Number of worker processes to use. Default is 5.
    - metadata_file: str, optional
        Path to metadata JSON file for filtering. Default is None.
    - min_length: int, optional
        Minimum length of PDF to convert. Default is None.
    """

    in_folder = os.path.abspath(in_folder)
    out_folder = os.path.abspath(out_folder)
    files = [os.path.join(in_folder, f) for f in os.listdir(in_folder)]
    files = [f for f in files if os.path.isfile(f)]
    os.makedirs(out_folder, exist_ok=True)

    # Handle chunks if we're processing in parallel
    # Ensure we get all files into a chunk
    chunk_size = math.ceil(len(files) / num_chunks)
    start_idx = chunk_idx * chunk_size
    end_idx = start_idx + chunk_size
    files_to_convert = files[start_idx:end_idx]

    # Limit files converted if needed
    if max:
        files_to_convert = files_to_convert[:max_files]

    metadata = {}
    if metadata_file:
        metadata_file = os.path.abspath(metadata_file)
        with open(metadata_file, "r") as f:
            metadata = json.load(f)

    total_processes = min(len(files_to_convert), workers)

    # Dynamically set GPU allocation per task based on GPU ram
    if inference_ram is not None:
        settings.INFERENCE_RAM = inference_ram
    if vram_per_task is not None:
        settings.VRAM_PER_TASK = vram_per_task

    if settings.CUDA:
        tasks_per_gpu = (
            settings.INFERENCE_RAM // settings.VRAM_PER_TASK if settings.CUDA else 0
        )
        total_processes = int(min(tasks_per_gpu, total_processes))
    else:
        total_processes = int(total_processes)

    mp.set_start_method("spawn")  # Required for CUDA, forkserver doesn't work
    model_lst = load_all_models()

    for model in model_lst:
        if model is None:
            continue

        if model.device.type == "mps":
            raise ValueError(
                "Cannot use MPS with torch multiprocessing share_memory.  You have to use CUDA or CPU.  Set the TORCH_DEVICE environment variable to change the device."
            )

        model.share_memory()

    print(
        f"Converting {len(files_to_convert)} pdfs in chunk {chunk_idx + 1}/{num_chunks} with {total_processes} processes, and storing in {out_folder}"
    )
    task_args = [
        (f, out_folder, metadata.get(os.path.basename(f)), min_length)
        for f in files_to_convert
    ]

    with mp.Pool(
        processes=total_processes, initializer=worker_init, initargs=(model_lst,)
    ) as pool:
        list(
            tqdm(
                pool.imap(process_single_pdf, task_args),
                total=len(task_args),
                desc="Processing PDFs",
                unit="pdf",
            )
        )

        pool._worker_handler.terminate = worker_exit

    # Delete all CUDA tensors
    del model_lst