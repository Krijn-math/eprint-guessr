import requests
import fitz  # PyMuPDF
import random
import io
from PIL import Image
import numpy as np
from bs4 import BeautifulSoup
import urllib.parse
import re
from math import log
from os import system
import matplotlib.pyplot as plt
from semanticscholar import SemanticScholar


# TODO: fix bad pdfs
# TODO: fix scoring cites

#globals 

zoom = 2.0                          # 2x zoom = 192 dpi
top_fraction = 0.4
min_abstract_length = 15
max_abstract_length = 100           # prevents shitty two-column papers
min_abstract_gray = 240

padsides = 80
padtop = 100
padbot = 100

weights = {
    2000: 69,
    2001: 113,
    2002: 195,
    2003: 265,
    2004: 377,
    2005: 469,
    2006: 486,
    2007: 482,
    2008: 545,
    2009: 638,
    2010: 661,
    2011: 714,
    2012: 733,
    2013: 882,
    2014: 1029,
    2015: 1257,
    2016: 1196,
    2017: 1262,
    2018: 1251,
    2019: 1499,
    2020: 1620,
    2021: 1705,
    2022: 1781,
    2023: 1973,
    2024: 2100
}

tot_papers = sum(weights.values())

def random_paper():
    id = random.randint(0, tot_papers)
    year = 2000
    year_tot = 0
    while True:
        year_tot += weights[year]
        year += 1
        if year_tot + weights[year] > id:
            break
    
    paperid = id - year_tot
    assert paperid < weights[year]
    return year, paperid

def get_png(year, id):
    url = f"https://eprint.iacr.org/{year}/{id}.pdf"
    # Download PDF
    response = requests.get(url)
    pdf_bytes = io.BytesIO(response.content)
    # Open PDF
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    # print("got pdf")

    # Get first page
    page = doc.load_page(0)

    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)

    # pix = page.get_pixmap()
    
    return pix

def crop_png(pix):

    # Convert pix to grayscale NumPy array
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).convert("L")
    arr = np.array(img)

    N = 5*int(zoom)  # rows per block
    h = arr.shape[0]
    num_blocks = h // N
    block_means = arr[:num_blocks * N].reshape(num_blocks, N, -1).mean(axis=(1, 2))
    data = np.array(block_means)

    subarrays = []
    block_row_starts = []  # absolute row of each block start

    row_counter = 0
    in_block = False
    block_vals = []

    for val in data:
        if val < 255:
            if not in_block:
                block_row_starts.append(row_counter * N)  # store pixel row start
                block_vals = []
                in_block = True
            block_vals.append(val)
        elif in_block:
            block_vals = np.array(block_vals)
            k = max(1, int(len(block_vals) * top_fraction))
            top_vals = np.sort(block_vals)[:k]  # correct: top 40%
            subarrays.append([top_vals.mean(), len(block_vals)])
            block_vals = []
            in_block = False
        row_counter += 1

    if in_block:
        block_vals = np.array(block_vals)
        k = max(1, int(len(block_vals) * top_fraction))
        top_vals = np.sort(block_vals)[:k]
        subarrays.append([top_vals.mean(), len(block_vals)])

    # print(subarrays)

    # Heuristic: detect abstract

    abstract_block_index = None
    for i, (mean_val, length) in enumerate(subarrays):
        if length >= min_abstract_length and length <= max_abstract_length and mean_val <= min_abstract_gray:
            abstract_block_index = i
            break

    if abstract_block_index is None:
        return 0 
    else:
        end_block = abstract_block_index
        while end_block + 1 < len(subarrays) and subarrays[end_block + 1][1] >= min_abstract_length:
            end_block += 1

        # Use absolute row from block_row_starts + block height in rows
        crop_row = block_row_starts[end_block] + subarrays[end_block][1] * N
        crop_row = min(crop_row, pix.height) + 10

    # Crop and save
    cropped = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).crop((padsides + 20, padtop, pix.width - padsides, crop_row))
    
    width, height = cropped.size
    cropped_pad = Image.new("RGB", (width, height + padbot), (255, 255, 255))
    cropped_pad.paste(cropped, (0, 0))

    return cropped_pad

def random_png():
    while True:
        year, id = random_paper()
        png = get_png(year, id)
        cropped = crop_png(png)
        if cropped:
            break
    return cropped, year, id


def get_title(year, id):
    url = f"https://eprint.iacr.org/{year}/{id}"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    # Find the h3 element with class "mb-3"
    h3 = soup.find("h3", class_="mb-3")

    if h3:
        return h3.text
    
def get_cites(title):    
    sch = SemanticScholar()
    paper = sch.search_paper(query=title, match_title=True)

    citations = paper.citationCount

    if citations is not None:
        return citations

    return False

def round(score, index):
    while True:
        cropped, year, id = random_png()
        title = get_title(year, id)
        cite = get_cites(title)
        if cite != False:
            break 
    
    plt.imshow(cropped)
    plt.axis("off")
    plt.show(block=False)
    
    system('clear')

    print(f"\n\n        ROUND {index}\n\n")

    year_guess = int(input("        Enter the year of publication: "))
    cite_guess = int(input("        Enter the number of citations: "))

    year_dist = abs(year_guess - year)
    penalty = {
        0: 0,
        1: 100,
        2: 500,
        3: 1000,
        4: 2000,
        5: 4000,
    }

    if year_dist <= 5:
        year_score = 5000 - penalty[year_dist]
    else:
        year_score = 0

    cite_dist = abs(cite - cite_guess)
    cite_score = 5000 - min(
        max(cite, cite_guess) * cite_dist * 10,
        5000)

    print(f"\n        Actual year: {year}")
    print(f"        Actual cites: {cite}\n")

    print(f"        Score for year: {year_score} / 5000")
    print(f"        Score for cite: {cite_score} / 5000")
    print(f"        Round score:    {year_score + cite_score} / 10000\n\n")
    
    score += year_score + cite_score
    index += 1
    
    print(f"        Total score:    {score} / {index*10000}\n\n")
    
    another = str(input("        Another round (y/n)? "))
    
    plt.close()
    
    if another == 'y':
        return round(score, index)
    else:
        return score, index
    

round(0, 1)

