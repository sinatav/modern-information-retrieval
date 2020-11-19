from __future__ import unicode_literals
import pandas as pd
import xml.etree.ElementTree as ET
import pickle

import src.compression as compress
import src.text_processing as proc_text
from prompt_toolkit.shortcuts import ProgressBar

import threading
from pathlib import Path


class MIR:
    def __init__(self, files_root: str = './files', output_root: str = './outputs'):
        self.files_root = files_root
        self.output_root = output_root
        self.persian_wikis = []
        self.ted_talk_title = []
        self.ted_talk_desc = []
        self.positional_indices = dict()  # key: word value: dict(): key: doc ID, value: list of positions
        self.coded_indices = dict()  # key: word value: dict(): key: doc ID, value: bytes of indices
        self.bigram_indices = dict()  # key: bi-gram value: dict(): key: word, value: collection freq
        self.collections = []
        self.collections_deleted = []  # vector indicating whether the corresponding document is deleted or not
        # creating output root
        Path(self.output_root).mkdir(parents=True, exist_ok=True)
        self.positional_add = 'outputs/pos.pickle'
        self.bigram_add = 'outputs/bi.pickle'
        self.coded_add = 'outputs/coded.pickle'

    def _load_talks(self, pb=None):
        talks = pd.read_csv(f'{self.files_root}/ted_talks.csv')
        self.ted_talk_title = talks['title'].to_list()
        self.ted_talk_desc = talks['description'].to_list()
        for talk_id in pb(range(len(self.ted_talk_title)), label='Ted Talks') if pb is not None else range(
                len(self.ted_talk_title)):
            self.collections.append(
                'title: ' + self.ted_talk_title[talk_id] + '\n' + 'desc: ' + self.ted_talk_desc[talk_id])
            self.collections_deleted.append(False)
            self.insert(self.ted_talk_title[talk_id], 'eng', len(self.collections) - 1)
            self.insert(self.ted_talk_desc[talk_id], 'eng', len(self.collections) - 1)

    def _load_wikis(self, pb=None):
        root = ET.parse(f'{self.files_root}/Persian.xml').getroot()
        for child in pb(root, label='Persian Wikis') if pb is not None else root:
            for chil in child:
                if chil.tag[-8:] == 'revision':
                    for ch in chil:
                        if ch.tag[-4:] == 'text':
                            self.persian_wikis.append(ch.text)
                            self.insert(ch.text, 'persian')

    def load_datasets(self):
        """loads datasets"""
        with ProgressBar(title='Loading Datasets') as pb:
            t1 = threading.Thread(target=self._load_talks, args=(pb,), daemon=True)
            t2 = threading.Thread(target=self._load_wikis, args=(pb,), daemon=True)
            t1.start()
            t2.start()
            for t in [t1, t2]:
                while t.is_alive():
                    t.join(timeout=.5)

    def insert(self, document, lang="eng", doc_id=None):
        """insert a document"""
        if doc_id is None:
            self.collections.append(document)
            self.collections_deleted.append(False)
            doc_id = len(self.collections) - 1
        terms = proc_text.prepare_text(document, lang, False)

        # Bi-gram
        words = list(set(terms))
        for word in words:
            bis = proc_text.bigram_word(word)
            for bi in bis:
                if bi not in self.bigram_indices.keys():
                    self.bigram_indices[bi] = dict()

                if word not in self.bigram_indices[bi].keys():
                    self.bigram_indices[bi][word] = 1
                else:
                    self.bigram_indices[bi][word] += 1

        # Positional
        for i in range(len(terms)):
            term = terms[i]
            if term not in self.positional_indices.keys():
                self.positional_indices[term] = dict()
            if doc_id not in self.positional_indices[term].keys():
                self.positional_indices[term][doc_id] = []
            self.positional_indices[term][doc_id].append(i)

    def delete(self, document, lang, doc_id=None):
        if doc_id is None:
            doc_id = self.collections.index(document)
            self.collections_deleted[doc_id] = True
        tokens = proc_text.prepare_text(document, lang)

        # Bigram
        words = list(set(tokens))
        for word in words:
            bis = proc_text.bigram_word(word)
            for bi in bis:
                self.bigram_indices[bi][word] -= 1
                if self.bigram_indices[bi][word] == 0:
                    del self.bigram_indices[bi][word]
                if len(self.bigram_indices[bi].keys()) == 0:
                    del self.bigram_indices[bi]

        # Positional
        keys_to_del = []
        for key in self.positional_indices.keys():
            if doc_id in self.positional_indices[key].keys():
                del self.positional_indices[key][doc_id]
            if len(self.positional_indices[key].keys()) == 0:
                keys_to_del.append(key)
        for kdl in keys_to_del:
            del self.positional_indices[kdl]

    def posting_list_by_word(self, word, lang):
        token = proc_text.prepare_text(word, lang, verbose=False)[0]
        print(self.positional_indices[token])

    def words_by_bigram(self, bigram: str):
        print(self.bigram_indices[bigram].keys())

    def save_indices(self):
        with open(self.positional_add, 'wb') as handle:
            pickle.dump(self.positional_indices, handle, protocol=pickle.HIGHEST_PROTOCOL)
        with open(self.bigram_add, 'wb') as handle:
            pickle.dump(self.bigram_indices, handle, protocol=pickle.HIGHEST_PROTOCOL)

    def load_indices(self):
        with open(self.positional_add, 'rb') as handle:
            self.positional_indices = pickle.load(handle)
        with open(self.bigram_add, 'rb') as handle:
            self.bigram_indices = pickle.load(handle)

    def save_coded_indices(self):  # todo: arvin bitarray
        self.code_indices()
        with open(self.coded_add, 'wb') as handle:
            pickle.dump(self.coded_indices, handle, protocol=pickle.HIGHEST_PROTOCOL)
        with open(self.bigram_add, 'wb') as handle:
            pickle.dump(self.bigram_indices, handle, protocol=pickle.HIGHEST_PROTOCOL)

    def load_coded_indices(self):  # todo: arvin bitarray
        with open(self.coded_add, 'rb') as handle:
            self.coded_indices = pickle.load(handle)
        with open(self.bigram_add, 'rb') as handle:
            self.bigram_indices = pickle.load(handle)
        self.decode_indices()

    def code_indices(self, coding="s"):  # todo: arvin bitarray
        for word in self.positional_indices:
            self.coded_indices[word] = dict()
            for doc in self.positional_indices[word]:
                self.coded_indices[word][doc] = compress.gamma_code(
                    self.positional_indices[word][doc]) if coding == "gamma" else compress.variable_byte(
                    self.positional_indices[word][doc])

    def decode_indices(self, coding="s"):  # todo: arvin bitarray
        for word in self.coded_indices:
            self.positional_indices[word] = dict()
            for doc in self.coded_indices[word]:
                self.positional_indices[word][doc] = compress.decode_gamma_code(format(
                    self.coded_indices[word][doc], "b")) if coding == "gamma" else compress.decode_variable_length(
                    format(self.coded_indices[word][doc], "b"))
