import json
import pickle
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader, SequentialSampler
from datasets import load_dataset
import os
import spacy
import re
import random
import argparse
#from transformers import BertTokenizer, BertForMaskedLM, BertModel
#from bert_score import BERTScorer
#from evaluate import load
import numpy as np
from bert_score import score
from sklearn.metrics.pairwise import cosine_similarity
## First Try to inject sentiment  with commensense : existant model already 
# from transformers import pipeline
# sentiment_analysis = pipeline("sentiment-analysis",model="siebert/sentiment-roberta-large-english")
# Emotion analysis
from pysentimiento import create_analyzer
emotion_analyzer = create_analyzer(task="emotion", lang="en")

#in order to have comparable results
random.seed(9001)

class SamsumDataset(Dataset):
    def __init__(self, encoder_max_len, decoder_max_len, split_type, 
                 tokenizer, subset_size, relation, extra_context=False, extra_supervision=False, 
                 paracomet=False, supervision_relation="xIntent", 
                 roberta=False, sentence_transformer=False, sentiment = False):
        self.encoder_max_len = encoder_max_len
        self.decoder_max_len = decoder_max_len
        self.split_type = split_type
        self.tokenizer = tokenizer
        self.subset_size = subset_size
        self.sentiment = sentiment
        self.extra_context=extra_context
        self.extra_supervision=extra_supervision
        
        self.relation = relation
        self.paracomet = paracomet
        if self.paracomet and (self.relation[0] != "<"):
            self.relation = f"<|{self.relation}|>"
            
        
        self.supervision_relation = supervision_relation
        if self.paracomet and (self.supervision_relation[0] != "<"):
            self.supervision_relation = f"<|{self.supervision_relation}|>"

        self.roberta = roberta
        self.sentence_transformer = sentence_transformer
        print(self.relation)
        ##################################################
        #dict(random.sample(d.items(), n))

        self.data = load_dataset('samsum',split=split_type)
        if self.subset_size != 100:
          subset_indices = random.sample(range(len(self.data)), int((self.subset_size)/100 * int(len(self.data))))
          self.data = self.data.select(subset_indices)
        self.dialogue = self.data['dialogue']
        self.summary = self.data['summary']
        self.id = self.data['id']

        self.nlp = spacy.load('en_core_web_sm')
        


        
        ###########################
        #   LOAD .json dataset    #
        ###########################
        if self.extra_context==True:
            if self.paracomet==False:
                ##### COMET #####
                with open(f"../data/COMET_data/comet/dialogue/samsum/comet_{self.split_type}.json") as f:
                    self.dialogue_comet_inference = json.load(f)
                
                if self.roberta:
                    print('ROBERTA ON!')
                    with open(f"../data/COMET_data/comet/dialogue/samsum/roberta_nli/roberta_classified_top1_{self.split_type}.json") as f:
                        self.roberta_classified_z = json.load(f)
                if self.sentence_transformer:
                    with open(f"../data/COMET_data/comet/dialogue/samsum/sentence_transformer/comet_{self.split_type}_z.json") as f:
                        self.sentence_transformer_classified_z = json.load(f)
                        
                    
            else:
                
                with open(f"../data/COMET_data/paracomet/dialogue/samsum/dialog_{self.split_type}_split5_collated.json") as f:
                    self.dialogue_comet_inference = json.load(f)
                if self.roberta:
                    print('ROBERTA ON!')
                    with open(f"../data/COMET_data/paracomet/dialogue/samsum/roberta_nli/paracomet_samsum_roberta_classified_top1_{self.split_type}.json") as f:
                        self.roberta_classified_z = json.load(f)
                if self.sentence_transformer:
                    with open(f"../data/COMET_data/paracomet/dialogue/samsum/sentence_transformer/paracomet_{self.split_type}_z.json") as f:
                        self.sentence_transformer_classified_z = json.load(f)
                    
              
        
        if self.extra_supervision==True: # use commonsense w
            if self.split_type=='train':
                if self.paracomet==False: # plain COMET
                    with open(f"../data/COMET_data/comet/summary/samsum/comet_train_w.json") as f:
                        self.summary_comet_inference = json.load(f)

                    if self.roberta:
                        print('ROBERTA ON!')
                        with open(f"../data/COMET_data/comet/summary/samsum/roberta_nli/roberta_classified_top1_w.json") as f:
                            self.roberta_classified_w = json.load(f)
                    if self.sentence_transformer:
                        with open(f"../data/COMET_data/comet/summary/samsum/sentence_transformer/comet_train_w.json") as f:
                            self.sentence_transformer_classified_w = json.load(f)
                else:
                    with open(f"../data/COMET_data/paracomet/summary/samsum/summary_train_split5_collated.json") as f:
                        self.summary_comet_inference = json.load(f)
                    if self.roberta:
                        print('ROBERTA ON!')
                        with open(f"../data/COMET_data/paracomet/summary/samsum/roberta_nli/roberta_classified_top1_w.json") as f:
                            self.roberta_classified_w = json.load(f)
                    
                    if self.sentence_transformer:
                        with open(f"../data/COMET_data/paracomet/summary/samsum/sentence_transformer/paracomet_train_w.json") as f:
                            self.sentence_transformer_classified_w = json.load(f)
        
        self.data_len = len(self.data)

        # total = [i for i in range(self.data_len)]
        # self.low_res = random.sample(total,self.data_len/10)
        # print(self.low_res)


    def compute_best_relation(self, sentence, d: dict):
      print(f"Sentence: {sentence}")
      encoded_sentence = self.tokenizer(sentence,
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.encoder_max_len, 
                                            return_tensors='pt')
      commonsenseDict = {}
      if self.paracomet:
        commonsenseDict['xReact'] = d['<|xReact|>'][0]
        commonsenseDict['xWant'] = d['<|xWant|>'][0]
        commonsenseDict['xIntent'] = d['<|xIntent|>'][0]
        commonsenseDict['xAttr'] = d['<|xAttr|>'][0]
        commonsenseDict['xEffect'] = d['<|xEffect|>'][0]
      else:
        commonsenseDict['HinderedBy'] = d['HinderedBy'][0]
        commonsenseDict['xWant'] = d['xWant'][0]
        commonsenseDict['xIntent'] = d['xIntent'][0]
        commonsenseDict['xNeed'] = d['xNeed'][0]
        commonsenseDict['xReason'] = d['xReason'][0]

      print(commonsenseDict)
        
      for k, v in commonsenseDict.items():
        encoded = self.tokenizer(v, padding='max_length', 
                                              truncation=True, 
                                              max_length=self.encoder_max_len, 
                                              return_tensors='pt')
        similarity = cosine_similarity(encoded_sentence['input_ids'], encoded['input_ids'])
        commonsenseDict[k] = similarity[0][0]
      
      print(commonsenseDict)
      print(f"The best relation is: {max(commonsenseDict, key=commonsenseDict.get)}")
      return max(commonsenseDict, key=commonsenseDict.get)

    def process_media_msg(self,sentence, person, commonsense, previous):
        # print(person)
        if ('<file_photo>' in sentence) or ('<photo_file>' in sentence) or ('<file_picture>' in sentence):
            return "<I> " + person + " sent a photo. </I>" + '\n' 
        elif ('<video>' in sentence) or ('<file_video>' in sentence):
            return "<I> " + person + " sent a video. </I>" + '\n'
        elif '<file_gif>' in sentence:
            return "<I> " + person + " sent a file. </I>" + '\n'
        elif ('<file_other>' in sentence) or ('<file_others>' in sentence):
            return "<I> " + person + " sent a file. </I>" + '\n'
        elif ('<link>' in sentence) or ('<file_link>' in sentence):
            return "<I> " + person + " sent a link. </I>" + '\n'
        elif '<location>' in sentence:
            return "<I> " + person + " sent a location. </I>" + '\n'
        else:
            if commonsense.strip() != 'none':
                ## ADD sentiment
                if self.sentiment == True :
                    emotion = emotion_analyzer.predict(sentence).output
                    if emotion == "others" :
                        emotion2 = emotion_analyzer.predict(previous).output 
                        #if emotion2!="others" :
                            #print("new emotion detected is", emotion2, "to" ,sentence)
                        # #print("--------------------- New emotion  : ", emotion)
                        return "<I> " + commonsense.strip() + "," + emotion2 + ". </I>" + '\n'
                    return "<I> " + commonsense.strip() + "," + emotion + ". </I>" + '\n'
                else : 
                    return "<I> " + commonsense.strip() + ". </I>" + '\n'
            else:
                return "" 



    def __len__(self):
        return self.data_len

    def __getitem__(self, index):
        if self.extra_context==False:
            #(1, sequence_length)
            encoded_dialogue = self.tokenizer(self.dialogue[index], 
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.encoder_max_len, 
                                            return_tensors='pt')
        else:
            if self.paracomet==False: # plain COMET
                try:
                    
                    dia = self.dialogue_comet_inference[self.id[index]]
                    n = len(dia)
                    dialogue=""
                    dialogue_clean = ""
                    previous = []
                    for sent_idx, sent in enumerate(dia):
                        person = sent['speaker'].replace(": ","").replace(":","").strip()
                        sentence = sent['sentence'].strip()
                        if self.roberta:
                            commonsense = self.roberta_classified_z[self.id[index]][str(sent_idx)]["out"]

                        elif self.sentence_transformer:
                            commonsense = self.sentence_transformer_classified_z[self.id[index]][str(sent_idx)]["out"]
                            # print(commonsense)
                        elif self.relation == 'best_relation':
                            commonsense = self.compute_best_relation(sentence, sent)
                        else:
                            commonsense = sent[self.relation][0].strip()

                        commonsense = commonsense.replace("PersonX","Person").replace("PersonY","Person")
                        dialogue += person + " said \"" + sentence + ".\"" + '\n'
                        dialogue_clean +=  person + " said \"" + sentence + ".\"" + '\n' 
                        if sent['speaker']+sentence != commonsense:
                            try :
                                ## Not include the commensense => 10 uteerances
                                previous = '\n'.join(line for line in dialogue_clean.splitlines()[-10:] if not line.strip().startswith('<I>'))
                                ## Includes the commensense in the process of the previous utterances 
                                #previous = '\n'.join(dialogue_clean.splitlines()[-5:])
                            except KeyError:
                              previous = dialogue_clean
                            dialogue += self.process_media_msg(sentence, person, commonsense, previous)


                except KeyError:
                    print("key error")
                    dialogue = self.dialogue[index]

                   
                        
            else: # use PARACOMET
                try:
                    dia = self.dialogue_comet_inference[self.id[index]]
                    #print(dia)
                    dialogue=""
                    dialogue_clean = ""
                    for sent_idx, sent in dia.items():
                        sentence = sent['sentence'].strip()
                        person = sentence.split()[0]
                        if self.roberta:
                            commonsense = self.roberta_classified_z[self.id[index]][str(sent_idx)]["out"]
                            
                        elif self.sentence_transformer:
                            commonsense = self.sentence_transformer_classified_z[self.id[index]][str(sent_idx)]["out"]
                        elif self.relation ==  '<|best_relation|>':    
                            commonsense = self.compute_best_relation(sentence, sent)
                            print(commonsense)
                        else:
                            #commonsense = sent[self.relation][0].strip() "xReason" is not present in PARACOMET 
                            commonsense = sent['<|xIntent|>'][0].strip()
                            
                        dialogue_clean += sentence +'\n'
                        dialogue += sentence +'\n'
                        if sentence != commonsense:
                            try : 
                                previous = '\n'.join(dialogue_clean.splitlines()[-10:])
                            except KeyError:
                                previous = dialogue_clean
                            dialogue += self.process_media_msg(sentence, person, commonsense, previous)
                            #print(previous)
                            
                except KeyError: # when an error occurred while processing commonsense, just give plain utterance as output
                    print("key error")
                    # print(index)
                    # print(self.id[index])
                    # print(self.dialogue_comet_inference.keys())
                    dialogue = self.dialogue[index]
             

            encoded_dialogue = self.tokenizer(dialogue,
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.encoder_max_len, 
                                            return_tensors='pt')


        # (1, sequence_length)
        with self.tokenizer.as_target_tokenizer():
            encoded_summary = self.tokenizer(self.summary[index], 
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.decoder_max_len, 
                                            return_tensors='pt')
        
            
        
        model_inputs = encoded_dialogue
        model_inputs['input_ids'] = model_inputs['input_ids'].squeeze(0)
        model_inputs['attention_mask'] = model_inputs['attention_mask'].squeeze(0)
        model_inputs['labels'] = encoded_summary['input_ids'].squeeze(0)

        if self.extra_supervision==True:
            if self.split_type=='train':
                def split_sentences(text, speaker):
                    doc = self.nlp(text)
                    sents = [speaker.replace(":","") + ' said "' + sent.text + '"' for sent in doc.sents]
                    return sents

                if self.paracomet==False: # plain COMET
                    summary_commonsense = ""
                    if self.roberta:
                        for _, summ in self.roberta_classified_w[self.id[index]].items():
                            commonsense = summ["out"].strip() + ". "
                            commonsense = commonsense.replace("PersonX","Person").replace("PersonY","Person")
                            summary_commonsense += commonsense
                    elif self.sentence_transformer:
                        for _, summ in self.sentence_transformer_classified_w[self.id[index]].items():
                            commonsense = summ["out"].strip() + ". "
                            commonsense = commonsense.replace("PersonX","Person").replace("PersonY","Person")
                            summary_commonsense += commonsense
                    else:
                        for summ in self.summary_comet_inference[self.id[index]]:
                            commonsense = summ[self.supervision_relation][0].strip() +'. '
                            commonsense = commonsense.replace("PersonX","Person").replace("PersonY","Person")
                            summary_commonsense += commonsense

                    with self.tokenizer.as_target_tokenizer():
                        encoded_extra_supervision = self.tokenizer(summary_commonsense,
                                                                padding='max_length',
                                                                truncation=True,
                                                                max_length=self.decoder_max_len,
                                                                return_tensors='pt')

                    model_inputs['extra_labels'] = encoded_extra_supervision['input_ids'].squeeze(0)
                else: 
                    if index==6054:
                        summary_commonsense = "problem with presentation."
                    elif self.roberta:
                        summary_commonsense = ""
                        for _, summ in self.roberta_classified_w[self.id[index]].items():
                            commonsense = summ["out"].strip() + ". "
                            commonsense = commonsense.replace("PersonX","Person").replace("PersonY","Person")
                            summary_commonsense += commonsense
                    elif self.sentence_transformer:
                        summary_commonsense = ""
                        for _, summ in self.sentence_transformer_classified_w[self.id[index]].items():
                            commonsense = summ["out"].strip().strip(".") + ". "
                            commonsense = commonsense.replace("PersonX","Person").replace("PersonY","Person")
                            summary_commonsense += commonsense
                    else:
                        summary_commonsense = ""
                        for _,summ in self.summary_comet_inference[self.id[index]].items():
                            try:
                                summary_commonsense += summ[self.supervision_relation][0].strip() +'. '
                            except KeyError:
                                print("key error in supervision")
                                summary_commonsense = ""

                    with self.tokenizer.as_target_tokenizer():
                        encoded_extra_supervision = self.tokenizer(summary_commonsense,
                                                                padding='max_length',
                                                                truncation=True,
                                                                max_length=self.decoder_max_len,
                                                                return_tensors='pt')

                    model_inputs['extra_labels'] = encoded_extra_supervision['input_ids'].squeeze(0)
                # print(summary_commonsense)
            
        return model_inputs





class SamsumDataset_total:
    def __init__(self, encoder_max_len, decoder_max_len, tokenizer, subset_size, relation, 
                 extra_context=False, extra_supervision=False, paracomet=False,
                 supervision_relation='isAfter',
                 roberta=False, sentence_transformer=False, sentiment = False):
        self.train_dataset = SamsumDataset(encoder_max_len, decoder_max_len, 'train',tokenizer,subset_size, relation, extra_context=extra_context,extra_supervision=extra_supervision,paracomet=paracomet, supervision_relation=supervision_relation, roberta=roberta, sentence_transformer=sentence_transformer, sentiment = sentiment)
        self.eval_dataset = SamsumDataset(encoder_max_len, decoder_max_len, 'validation', tokenizer,subset_size, relation, extra_context=extra_context,extra_supervision=extra_supervision,paracomet=paracomet, supervision_relation=supervision_relation, roberta=roberta, sentence_transformer=sentence_transformer,  sentiment = sentiment)
        self.test_dataset = SamsumDataset(encoder_max_len, decoder_max_len, 'test', tokenizer,100, relation, extra_context=extra_context,extra_supervision=extra_supervision,paracomet=paracomet, supervision_relation=supervision_relation, roberta=roberta, sentence_transformer=sentence_transformer,  sentiment = sentiment)
    
    def getTrainData(self):
        return self.train_dataset
    
    def getEvalData(self):
        return self.eval_dataset

    def getTestData(self):
        return self.test_dataset


def custom_load_dataset(type,split):
    if type == "dialogsum":
        dir = f"../data/DialogSum_Data/dialogsum.{split}.jsonl"
        data = {'dialogue': [],'summary':[],'id':[]}
        with open(dir, 'r') as json_file:
            json_list = list(json_file)
        if split == "train":
            for json_str in json_list:
                result = json.loads(json_str)
                data['dialogue'].append(result['dialogue'])
                data['summary'].append((result['summary']))
                data['id'].append((result['fname'][6:]))
        elif split == "validation":
            for json_str in json_list:
                result = json.loads(json_str)
                data['dialogue'].append(result['dialogue'])
                data['summary'].append((result['summary']))
                data['id'].append((result['fname'][4:]))
        elif split == "test":
            data = {'dialogue': [],'summary':[],'id':[], 'summary2':[], 'summary3':[]}
            for json_str in json_list:
                result = json.loads(json_str)
                data['dialogue'].append(result['dialogue'])
                data['summary'].append((result['summary1']))
                data['summary2'].append((result['summary2']))
                data['summary3'].append((result['summary3']))
                data['id'].append((result['fname'][5:]))
        else:
            print("non-existing")
            os.exit()
        return data
    elif type == "tweetsumm":
        dialogs_dir = f"../data/Tweetsumm_Data/{split}_dialogs.json"
        summaries_dir = f"../data/Tweetsumm_Data/{split}_summaries.json"
        data = {'dialogue': [],'summary':[],'id':[]}
        with open(dialogs_dir, 'r') as json_file:
            all_dialogs = json.load(json_file)
            for key in all_dialogs.keys():
                dialog = ''
                data['id'].append(key[len(split)+1:])
                for sent in all_dialogs[key]:
                    sentence = sent['sentence'].replace('\n','')
                    author = sent['author_id']
                    dialog += f"#{author}#: {sentence}\n"
                data['dialogue'].append(dialog)

        with open(summaries_dir, 'r') as json_file:
            all_summaries = json.load(json_file)
            for key in all_summaries.keys():
                summ = ''
                for sent in all_summaries[key]:
                    summ += sent
                data['summary'].append(summ)
        return data


class DialogsumDataset(Dataset):
    def __init__(self, encoder_max_len, decoder_max_len, split_type, tokenizer, subset_size, extra_context=False, extra_supervision=False, paracomet=False, relation="xReason", supervision_relation="isAfter", roberta=False, sentence_transformer=False, sentiment = False):
        self.encoder_max_len = encoder_max_len
        self.decoder_max_len = decoder_max_len
        self.split_type = split_type
        self.tokenizer = tokenizer
        self.subset_size = subset_size
        self.sentiment = sentiment
        self.extra_context=extra_context
        self.extra_supervision=extra_supervision
        
        self.relation = relation
        self.paracomet= paracomet
        
        self.roberta=roberta
        self.sentence_transformer = sentence_transformer

        if (self.paracomet) and ("<" != self.relation[0]):
            self.relation = f"<|{self.relation}|>"

        self.supervision_relation = supervision_relation
        if not self.sentence_transformer:
            print(self.relation)

        else:
            if self.paracomet:
                print("PARACOMET sentence-transformer")
            else:
                print("COMET sentence-transformer")

        ##################################################

        self.data = custom_load_dataset('dialogsum', split=split_type)
        #print(len(self.data['dialogue']), len(self.data['id']), len(self.data['summary'])) All the same
        if self.subset_size != 100 and (split_type == 'train' or split_type == 'validation'):
          selected_indices = random.sample(range(len(self.data['dialogue'])), int((self.subset_size)/100 * len(self.data['dialogue'])))
          #print(selected_indices, len(selected_indices))
          #self.data = dict(random.sample(self.data.items(), int((self.subset_size)/100 * len(self.data))))
          #subset_indices = random.sample(range(len(self.data)), int((self.subset_size)/100 * int(len(self.data))))
          #self.data = self.data.select(subset_indices)
          #print(self.data)
          self.dialogue = [self.data["dialogue"][i]  for i in selected_indices]
          self.summary = [self.data["summary"][i]  for i in selected_indices]
          self.id = [self.data["id"][i]  for i in selected_indices]
        else:
          self.dialogue = self.data['dialogue']
          self.summary = self.data['summary']
          self.id = self.data['id']
        if split_type == "test":
            self.summary2 = self.data['summary2']
            self.summary3 = self.data['summary3']
            self.id = self.data['id']

        self.nlp = spacy.load('en_core_web_sm')
        
        if self.extra_context==True:
            if self.paracomet==False:
                ###########################
                # CODE FOR COMET 
                ###########################
                
                with open(f"../data/COMET_data/comet/dialogue/dialogsum/comet_{self.split_type}.json") as f:
                    self.dialogue_comet_inference = json.load(f)

                if self.roberta:
                    with open(f"../data/COMET_data/comet/dialogue/dialogsum/roberta_nli/roberta_classified_top1_{self.split_type}.json") as f:
                        self.roberta_classified_z = json.load(f)

                if self.sentence_transformer:
                    with open(f"../data/COMET_data/comet/dialogue/dialogsum/sentence_transformer/comet_{self.split_type}_z.json", "r") as f:
                        self.sentence_transformer_classified_z = json.load(f)

                
            else:
                ###########################
                # CODE FOR PARACOMET
                ###########################
                
                with open(f"../data/COMET_data/paracomet/dialogue/dialogsum/dialog_{self.split_type}_split5_collated.json") as f:
                    self.dialogue_comet_inference = json.load(f)
                
                if self.roberta:
                    with open(f"../data/COMET_data/paracomet/dialogue/dialogsum/roberta_nli/paracomet_dialogsum_roberta_classified_top1_{self.split_type}.json") as f:
                        self.roberta_classified_z = json.load(f)

                if self.sentence_transformer:
                    with open(f"../data/COMET_data/paracomet/dialogue/dialogsum/sentence_transformer/paracomet_{self.split_type}_z.json", "r") as f:
                        self.sentence_transformer_classified_z = json.load(f)

               
        
        if self.extra_supervision==True:
            if self.split_type=='train':
                if self.paracomet==False:
                    ######################
                    # CODE FOR COMET
                    ######################
                    with open(f"../data/COMET_data/comet/summary/dialogsum/comet_train_w.json") as f:
                        self.summary_comet_inference = json.load(f)
                    
                    if self.roberta:
                        with open(f"../data/COMET_data/comet/dialogue/dialogsum/roberta_nli/roberta_classified_top1_w.json")as f:
                            self.roberta_classified_w = json.load(f)

                    if sentence_transformer:
                        with open(f"../data/COMET_data/comet/summary/dialogsum/sentence_transformer/comet_train_w.json", "r") as f:
                            self.sentence_transformer_classified_w = json.load(f)

                else:
                    ########################
                    # CODE FOR PARACOMET
                    ########################
                    with open("../data/COMET_data/paracomet/summary/dialogsum/summary_train_split5_collated.json") as f:
                        self.summary_comet_inference = json.load(f)
                    
                    if self.roberta:
                        with open("../data/COMET_data/paracomet/summary/dialogsum/roberta_nli/roberta_classified_top1_w.json") as f:
                            self.roberta_classified_w = json.load(f)

                    if sentence_transformer:
                        with open("../data/COMET_data/paracomet/summary/dialogsum/sentence_transformer/paracomet_train_w.json", "r") as f:
                            self.sentence_transformer_classified_w = json.load(f)

        self.data_len = len(self.id)

    def __len__(self):
        return self.data_len

    def __getitem__(self, index):
        if self.extra_context==False:
            #(1, sequence_length)
            encoded_dialogue = self.tokenizer(self.dialogue[index], 
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.encoder_max_len, 
                                            return_tensors='pt')
        else:
            if self.split_type == "validation":
                dialog_id = f"dev_{self.id[index]}"

            else:
                dialog_id = f"{self.split_type}_{self.id[index]}"
            if self.sentence_transformer:
                cur_dialog_data = self.sentence_transformer_classified_z[dialog_id]
                dialogue = ""
                for sentence_idx in range(len(cur_dialog_data.keys())):
                    sentence = cur_dialog_data[str(sentence_idx)]["sentence"]
                    relation = cur_dialog_data[str(sentence_idx)]["relation"]
                    commonsense = cur_dialog_data[str(sentence_idx)]["out"]

                    dialogue += sentence + "\n"
                    dialogue+= '<I> '
                    dialogue+= commonsense+'.'
                    dialogue+= ' </I>'+'\n'
            
            elif self.roberta:
                cur_dialog_data = self.roberta_classified_z[dialog_id]
                dialogue=""
                for sentence_idx in range(len(cur_dialog_data.keys())):
                    try:
                        sentence = cur_dialog_data[str(sentence_idx)]["sentence"]
                        relation = cur_dialog_data[str(sentence_idx)]["relation"]
                        commonsense = cur_dialog_data[str(sentence_idx)]["out"]

                        dialogue += sentence + "\n"
                        dialogue+= "<I> "
                        dialogue+= commonsense+"."
                        dialogue+= " </I>"+"\n"
                    except KeyError:
                        continue
                

            elif self.paracomet==False:
                #######################
                # CODE FOR COMET
                #######################
                # extra context exist 
                # z is available
                splitted_dialogue = self.dialogue[index].replace('\r\n','\n').split('\n')
                
                def split_sentences(text, speaker):
                    doc = self.nlp(text)
                    sents = [speaker.replace(":","") + ' said "' + sent.text + '"' for sent in doc.sents]
                    return sents
                
                splitted_sentences = []
                for idx, utterance in enumerate(splitted_dialogue):
                    speaker = re.search(".*?\:",utterance)[0]
                    utterance = utterance.replace(speaker,"").strip()
                    utterance = split_sentences(utterance,speaker)
                    splitted_sentences.extend(utterance)
                    
                dialogue= ""
                idx=0
                for utterance in splitted_sentences:
                    dialogue+= utterance+'\n'
                    if self.split_type=='train':
                        try:
                            while True:
                                if self.dialogue_comet_inference['train_'+self.id[index]][idx]['sentence'] not in ("#Person1#:","#Person2#:"):
                                    commonsense = self.dialogue_comet_inference['train_'+self.id[index]][idx][self.relation][0].strip()
                                    # commonsense = commonsense.replace("PersonX","Person").replace("PersonY","Person")
                                    break
                                else:
                                    idx+=1
                                continue
                        except:
                            continue
                    elif self.split_type=='validation':
                        try:
                            while True:
                                if self.dialogue_comet_inference['dev_'+self.id[index]][idx]['sentence'] not in ("#Person1#:","#Person2#:"):
                                    commonsense = self.dialogue_comet_inference['dev_'+self.id[index]][idx][self.relation][0].strip()
                                    commonsense = commonsense.replace("PersonX","Person").replace("PersonY","Person")
                                    break
                                else:
                                    idx+=1
                                continue
                        except:
                            continue
                    else: # self.split_type=='test':
                        try:
                            while True:
                                if self.dialogue_comet_inference['test_'+self.id[index]][idx]['sentence'] not in ("#Person1#:","#Person2#:"):
                                    commonsense = self.dialogue_comet_inference['test_'+self.id[index]][idx][self.relation][0].strip()
                                    # commonsense = commonsense.replace("PersonX","Person").replace("PersonY","Person")
                                    break
                                else:
                                    idx+=1
                                continue

                        except:
                            continue
                    if 'none' not in commonsense:
                        dialogue+= '<I> '
                        dialogue+= commonsense+'.'
                        dialogue+= ' </I>'+'\n'
                    idx+=1
            ############################### PARACOMET START #######################################################
            else:
                if self.split_type=='validation':
                    dia = self.dialogue_comet_inference['dev'+'_'+self.id[index]]
                else:
                    dia = self.dialogue_comet_inference[self.split_type+'_'+self.id[index]]
                dialogue=""
                for _,sent in dia.items():
                    sentence = sent['sentence'].strip()
                    person = sentence.split()[0]
                    commonsense = sent[self.relation][0].strip()

                    dialogue += sentence +'\n'

                    if sentence != commonsense:
                        if ('<file_photo>' in sentence) or ('<photo_file>' in sentence) or ('<file_picture>' in sentence):
                            dialogue += "<I> " + person + " sent a photo. </I>" + '\n' 
                        elif ('<video>' in sentence) or ('<file_video>' in sentence):
                            dialogue += "<I> " + person + " sent a video. </I>" + '\n'
                        elif '<file_gif>' in sentence:
                            dialogue += "<I> " + person + " sent a file. </I>" + '\n'
                        elif ('<file_other>' in sentence) or ('<file_others>' in sentence):
                            dialogue += "<I> " + person + " sent a file. </I>" + '\n'
                        elif ('<link>' in sentence) or ('<file_link>' in sentence):
                            dialogue += "<I> " + person + " sent a link. </I>" + '\n'
                        elif '<location>' in sentence:
                            dialogue += "<I> " + person + " sent a location. </I>" + '\n'
                        else:
                            if commonsense.strip() != 'none':
                                ## ADD sentiment
                                if self.sentiment == True :
                                    #sent = sentiment_analysis(sentence)[0]["label"]
                                    return "<I> " + commonsense.strip() + ". </I>" + '\n'
                                else : 
                                    return "<I> " + commonsense.strip() + ". </I>" + '\n'
                            else:
                                return "" 

            encoded_dialogue = self.tokenizer(dialogue,
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.encoder_max_len, 
                                            add_special_tokens=True,
                                            return_tensors='pt')

        # (1, sequence_length)
        #with self.tokenizer.as_target_tokenizer():
        encoded_summary = self.tokenizer(self.summary[index], 
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.decoder_max_len, 
                                            add_special_tokens=True,
                                            return_tensors='pt')
        
        
        model_inputs = encoded_dialogue
        model_inputs['input_ids'] = model_inputs['input_ids'].squeeze(0)
        model_inputs['attention_mask'] = model_inputs['attention_mask'].squeeze(0)
        model_inputs['labels'] = encoded_summary['input_ids']
        def shift_tokens_right(input_ids: torch.Tensor, pad_token_id: int, decoder_start_token_id: int):
            """
            Shift input ids one token to the right.
            """
            shifted_input_ids = input_ids.new_zeros(input_ids.shape)

            shifted_input_ids[:, 1:] = input_ids[:, :-1].clone()
            shifted_input_ids[:, 0] = decoder_start_token_id

            if pad_token_id is None:
                raise ValueError("self.model.config.pad_token_id has to be defined.")
            # replace possible -100 values in labels by `pad_token_id`
            shifted_input_ids.masked_fill_(shifted_input_ids == -100, pad_token_id)

            return shifted_input_ids

        #model_inputs['decoder_input_ids'] = shift_tokens_right(model_inputs['labels'].clone(),self.tokenizer.pad_token_id,0).squeeze(0)
        model_inputs['labels'] = model_inputs['labels'].squeeze(0)
        #print('#####')
        #print(model_inputs['decoder_input_ids'])
        #print()
        #print(model_inputs['labels'])
        #print('#####')
        #model_inputs['decoder_attention_mask'] = encoded_summary['attention_mask'].squeeze(0)
        


        if self.split_type == "test":
            encoded_summary2 = self.tokenizer(self.summary2[index], 
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.decoder_max_len, 
                                            return_tensors='pt')
            model_inputs['labels2'] = encoded_summary2['input_ids'].squeeze(0)


        
            encoded_summary3 = self.tokenizer(self.summary3[index], 
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.decoder_max_len, 
                                            return_tensors='pt')
            model_inputs['labels3'] = encoded_summary3['input_ids'].squeeze(0)

        


        if self.extra_supervision==True:
            if self.split_type=='train':
                if self.sentence_transformer:
                    cur_summary_commonsense_data = self.sentence_transformer_classified_w[f"train_{self.id[index]}"]
                    summary_commonsense = ""
                    for summary_sentence_idx in range(len(cur_summary_commonsense_data.keys())):
                        commonsense = cur_summary_commonsense_data[str(summary_sentence_idx)]["out"].strip()+" ."
                        summary_commonsense += commonsense

                    
                elif self.roberta:
                    cur_summary_commonsense_data =  self.roberta_classified_w[f"train_{self.id[index]}"]
                    summary_commonsense = ""
                    for summary_sentence_idx in range(len(cur_summary_commonsense_data.keys())):
                        commonsense = cur_summary_commonsense_data[str(summary_sentence_idx)]["out"].strip()+" ."
                        summary_commonsense += commonsense

                

                elif self.paracomet==False:
                    summary_commonsense = ""
                    for summ in self.summary_comet_inference["train_"+self.id[index]]:
                        commonsense = summ[self.supervision_relation][0].strip() +'. '
                        commonsense = commonsense.replace('PersonX','Person').replace('PersonY','Person')
                        summary_commonsense += commonsense

                ####################################### PARACOMET START ###########################################
                else:
                    summary_commonsense = ""
                    if self.split_type=='validation':
                        for _,summ in self.summary_comet_inference['dev'+'_'+self.id[index]].items():
                            summary_commonsense += summ[self.supervision_relation][0].strip() +'. '
                    else:
                        for _,summ in self.summary_comet_inference[self.split_type+'_'+self.id[index]].items():
                            summary_commonsense += summ[self.supervision_relation][0].strip() +'. '

                with self.tokenizer.as_target_tokenizer():
                    encoded_extra_supervision = self.tokenizer(summary_commonsense,
                                                            padding='max_length',
                                                            truncation=True,
                                                            max_length=self.decoder_max_len,
                                                            return_tensors='pt')

                model_inputs['extra_labels'] = encoded_extra_supervision['input_ids'].squeeze(0)
                    
        return model_inputs


class DialogsumDataset_total:
    def __init__(self, encoder_max_len, decoder_max_len, tokenizer, subset_size, 
                 extra_context=False, extra_supervision=False, paracomet=False, 
                 relation="xReason",roberta=False,supervision_relation='isAfter', 
                 sentence_transformer=False, sentiment = False):
        self.train_dataset = DialogsumDataset(encoder_max_len, decoder_max_len, 'train',tokenizer,subset_size, extra_context,extra_supervision,paracomet=paracomet,relation=relation,roberta=roberta,supervision_relation=supervision_relation, sentence_transformer=sentence_transformer,  sentiment = sentiment)
        self.eval_dataset = DialogsumDataset(encoder_max_len, decoder_max_len, 'validation', tokenizer,subset_size, extra_context,extra_supervision,paracomet=paracomet,relation=relation,roberta=roberta,supervision_relation=supervision_relation, sentence_transformer=sentence_transformer,  sentiment = sentiment)
        self.test_dataset = DialogsumDataset(encoder_max_len, decoder_max_len, 'test', tokenizer,100, extra_context,extra_supervision,paracomet=paracomet,relation=relation,roberta=roberta,supervision_relation=supervision_relation, sentence_transformer=sentence_transformer,  sentiment = sentiment)
        print(self.train_dataset.data_len)
    def getTrainData(self):
        return self.train_dataset
    
    def getEvalData(self):
        return self.eval_dataset

    def getTestData(self):
        return self.test_dataset

class MediasumDataset(Dataset):
    pass

class MediasumDataset_total:
    pass

class TweetsummDataset(Dataset):
    def __init__(self, encoder_max_len, decoder_max_len, split_type, tokenizer, subset_size, extra_context=False, extra_supervision=False, paracomet=False, relation="xReason", supervision_relation="isAfter", roberta=False, sentence_transformer=False, sentiment = False):
        self.encoder_max_len = encoder_max_len
        self.decoder_max_len = decoder_max_len
        self.split_type = split_type
        self.tokenizer = tokenizer
        self.subset_size = subset_size
        self.sentiment = sentiment
        self.extra_context=extra_context
        self.extra_supervision=extra_supervision
        
        self.relation = relation
        self.paracomet= paracomet
        
        self.roberta=roberta
        self.sentence_transformer = sentence_transformer

        self.supervision_relation = supervision_relation
        if not self.sentence_transformer:
            print(self.relation)

        else:
            if self.paracomet:
                print("PARACOMET sentence-transformer")
            else:
                print("COMET sentence-transformer")

        ##################################################

        self.data = custom_load_dataset('tweetsumm', split=split_type)
        #print(len(self.data['dialogue']), len(self.data['id']), len(self.data['summary'])) All the same
        if self.subset_size != 100 and (split_type == 'train' or split_type == 'validation'):
          selected_indices = random.sample(range(len(self.data['dialogue'])), int((self.subset_size)/100 * len(self.data['dialogue'])))
          #print(selected_indices, len(selected_indices))
          #self.data = dict(random.sample(self.data.items(), int((self.subset_size)/100 * len(self.data))))
          #subset_indices = random.sample(range(len(self.data)), int((self.subset_size)/100 * int(len(self.data))))
          #self.data = self.data.select(subset_indices)
          #print(self.data)
          self.dialogue = [self.data["dialogue"][i]  for i in selected_indices]
          self.summary = [self.data["summary"][i]  for i in selected_indices]
          self.id = [self.data["id"][i]  for i in selected_indices]
        else:
          self.dialogue = self.data['dialogue']
          self.summary = self.data['summary']
          self.id = self.data['id']
        
        
        self.nlp = spacy.load('en_core_web_sm')
        
        if self.extra_context==True:
            if self.paracomet==False:
                ###########################
                # CODE FOR COMET 
                ###########################
                
                with open(f"../data/COMET_data/comet/dialogue/tweetsumm/comet_{self.split_type}.json") as f:
                    self.dialogue_comet_inference = json.load(f)

                if self.roberta:
                    print("ROBERTA not available for tweetsumm")

                if self.sentence_transformer:
                    print("Sentence Transformer not available for tweetsumm")
                
            else:
                ###########################
                # CODE FOR PARACOMET
                ###########################
                print("PARACOMET not available for tweetsumm")

               
        
        if self.extra_supervision==True:
            if self.split_type=='train':
                if self.paracomet==False:
                    ######################
                    # CODE FOR COMET
                    ######################
                    with open(f"../data/COMET_data/comet/summary/tweetsumm/comet_train.json") as f:
                        self.summary_comet_inference = json.load(f)
                    
                    if self.roberta:
                        print("ROBERTA not available for tweetsumm")

                    if sentence_transformer:
                        print("Sentence Transformer not available for tweetsumm")

                else:
                    ########################
                    # CODE FOR PARACOMET
                    ########################
                    print("PARACOMET not available for tweetsumm")

        self.data_len = len(self.id)

    def __len__(self):
        return self.data_len

    def __getitem__(self, index):
        if self.extra_context==False:
            #(1, sequence_length)
            encoded_dialogue = self.tokenizer(self.dialogue[index], 
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.encoder_max_len, 
                                            return_tensors='pt')
        else:
            if self.split_type == "validation":
                dialog_id = f"dev_{self.id[index]}"

            else:
                dialog_id = f"{self.split_type}_{self.id[index]}"
            if self.sentence_transformer:
                cur_dialog_data = self.sentence_transformer_classified_z[dialog_id]
                dialogue = ""
                for sentence_idx in range(len(cur_dialog_data.keys())):
                    sentence = cur_dialog_data[str(sentence_idx)]["sentence"]
                    relation = cur_dialog_data[str(sentence_idx)]["relation"]
                    commonsense = cur_dialog_data[str(sentence_idx)]["out"]

                    dialogue += sentence + "\n"
                    dialogue+= '<I> '
                    dialogue+= commonsense+'.'
                    dialogue+= ' </I>'+'\n'
            
            elif self.roberta:
                print("ROBERTA not available for tweetsumm")
                

            elif self.paracomet==False:
                #######################
                # CODE FOR COMET
                #######################
                # extra context exist 
                # z is available
                splitted_dialogue = self.dialogue[index].replace('\r\n','\n').split('\n')
                
                def split_sentences(text, speaker):
                    doc = self.nlp(text)
                    sents = [speaker.replace(":","") + ' said "' + sent.text + '"' for sent in doc.sents]
                    return sents
                
                splitted_sentences = []
                for idx, utterance in enumerate(splitted_dialogue):
                    speaker_match = re.search(".*?:", utterance)
                    if speaker_match:
                        speaker = speaker_match.group()
                    else:
                      continue
                    

                    utterance = utterance.replace(speaker,"").strip()
                    utterance = split_sentences(utterance,speaker)
                    splitted_sentences.extend(utterance)

                dialogue= ""
                idx=0
                for utterance in splitted_sentences:
                    dialogue+= utterance+'\n'
                    if self.split_type=='train':
                        try:
                            while True:
                                if self.dialogue_comet_inference['train_'+self.id[index]][idx]['sentence'] not in ("#Person1#:","#Person2#:"):
                                    commonsense = self.dialogue_comet_inference['train_'+self.id[index]][idx][self.relation][0].strip()
                                    # commonsense = commonsense.replace("PersonX","Person").replace("PersonY","Person")
                                    break
                                else:
                                    idx+=1
                                continue
                        except:
                            continue
                    elif self.split_type=='validation':
                        try:
                            while True:
                                if self.dialogue_comet_inference['dev_'+self.id[index]][idx]['sentence'] not in ("#Person1#:","#Person2#:"):
                                    commonsense = self.dialogue_comet_inference['dev_'+self.id[index]][idx][self.relation][0].strip()
                                    commonsense = commonsense.replace("PersonX","Person").replace("PersonY","Person")
                                    break
                                else:
                                    idx+=1
                                continue
                        except:
                            continue
                    else: # self.split_type=='test':
                        try:
                            while True:
                                if self.dialogue_comet_inference['test_'+self.id[index]][idx]['sentence'] not in ("#Person1#:","#Person2#:"):
                                    commonsense = self.dialogue_comet_inference['test_'+self.id[index]][idx][self.relation][0].strip()
                                    # commonsense = commonsense.replace("PersonX","Person").replace("PersonY","Person")
                                    break
                                else:
                                    idx+=1
                                continue

                        except:
                            continue
                    if 'none' not in commonsense:
                        dialogue+= '<I> '
                        dialogue+= commonsense+'.'
                        dialogue+= ' </I>'+'\n'
                    idx+=1
            ############################### PARACOMET START #######################################################
            else:
                if self.split_type=='validation':
                    dia = self.dialogue_comet_inference['dev'+'_'+self.id[index]]
                else:
                    dia = self.dialogue_comet_inference[self.split_type+'_'+self.id[index]]
                dialogue=""
                for _,sent in dia.items():
                    sentence = sent['sentence'].strip()
                    person = sentence.split()[0]
                    commonsense = sent[self.relation][0].strip()

                    dialogue += sentence +'\n'

                    if sentence != commonsense:
                        if ('<file_photo>' in sentence) or ('<photo_file>' in sentence) or ('<file_picture>' in sentence):
                            dialogue += "<I> " + person + " sent a photo. </I>" + '\n' 
                        elif ('<video>' in sentence) or ('<file_video>' in sentence):
                            dialogue += "<I> " + person + " sent a video. </I>" + '\n'
                        elif '<file_gif>' in sentence:
                            dialogue += "<I> " + person + " sent a file. </I>" + '\n'
                        elif ('<file_other>' in sentence) or ('<file_others>' in sentence):
                            dialogue += "<I> " + person + " sent a file. </I>" + '\n'
                        elif ('<link>' in sentence) or ('<file_link>' in sentence):
                            dialogue += "<I> " + person + " sent a link. </I>" + '\n'
                        elif '<location>' in sentence:
                            dialogue += "<I> " + person + " sent a location. </I>" + '\n'
                        else:
                            if commonsense.strip() != 'none':
                                ## ADD sentiment
                                if self.sentiment == True :
                                    #sent = sentiment_analysis(sentence)[0]["label"]
                                    return "<I> " + commonsense.strip() + ". </I>" + '\n'
                                else : 
                                    return "<I> " + commonsense.strip() + ". </I>" + '\n'
                            else:
                                return "" 

            encoded_dialogue = self.tokenizer(dialogue,
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.encoder_max_len, 
                                            add_special_tokens=True,
                                            return_tensors='pt')

        # (1, sequence_length)
        #with self.tokenizer.as_target_tokenizer():
        encoded_summary = self.tokenizer(self.summary[index], 
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.decoder_max_len, 
                                            add_special_tokens=True,
                                            return_tensors='pt')
        
        
        model_inputs = encoded_dialogue
        model_inputs['input_ids'] = model_inputs['input_ids'].squeeze(0)
        model_inputs['attention_mask'] = model_inputs['attention_mask'].squeeze(0)
        model_inputs['labels'] = encoded_summary['input_ids']
        def shift_tokens_right(input_ids: torch.Tensor, pad_token_id: int, decoder_start_token_id: int):
            """
            Shift input ids one token to the right.
            """
            shifted_input_ids = input_ids.new_zeros(input_ids.shape)

            shifted_input_ids[:, 1:] = input_ids[:, :-1].clone()
            shifted_input_ids[:, 0] = decoder_start_token_id

            if pad_token_id is None:
                raise ValueError("self.model.config.pad_token_id has to be defined.")
            # replace possible -100 values in labels by `pad_token_id`
            shifted_input_ids.masked_fill_(shifted_input_ids == -100, pad_token_id)

            return shifted_input_ids

        #model_inputs['decoder_input_ids'] = shift_tokens_right(model_inputs['labels'].clone(),self.tokenizer.pad_token_id,0).squeeze(0)
        model_inputs['labels'] = model_inputs['labels'].squeeze(0)
        #print('#####')
        #print(model_inputs['decoder_input_ids'])
        #print()
        #print(model_inputs['labels'])
        #print('#####')
        #model_inputs['decoder_attention_mask'] = encoded_summary['attention_mask'].squeeze(0)
        


        if self.split_type == "test":
            encoded_summary2 = self.tokenizer(self.summary2[index], 
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.decoder_max_len, 
                                            return_tensors='pt')
            model_inputs['labels2'] = encoded_summary2['input_ids'].squeeze(0)


        
            encoded_summary3 = self.tokenizer(self.summary3[index], 
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.decoder_max_len, 
                                            return_tensors='pt')
            model_inputs['labels3'] = encoded_summary3['input_ids'].squeeze(0)

        


        if self.extra_supervision==True:
            if self.split_type=='train':
                if self.sentence_transformer:
                    cur_summary_commonsense_data = self.sentence_transformer_classified_w[f"train_{self.id[index]}"]
                    summary_commonsense = ""
                    for summary_sentence_idx in range(len(cur_summary_commonsense_data.keys())):
                        commonsense = cur_summary_commonsense_data[str(summary_sentence_idx)]["out"].strip()+" ."
                        summary_commonsense += commonsense

                    
                elif self.roberta:
                    print("ROBERTA not available for tweetsumm")

                elif self.paracomet==False:
                    summary_commonsense = ""
                    for summ in self.summary_comet_inference["train_"+self.id[index]]:
                        commonsense = summ[self.supervision_relation][0].strip() +'. '
                        commonsense = commonsense.replace('PersonX','Person').replace('PersonY','Person')
                        summary_commonsense += commonsense

                ####################################### PARACOMET START ###########################################
                else:
                    summary_commonsense = ""
                    if self.split_type=='validation':
                        for _,summ in self.summary_comet_inference['dev'+'_'+self.id[index]].items():
                            summary_commonsense += summ[self.supervision_relation][0].strip() +'. '
                    else:
                        for _,summ in self.summary_comet_inference[self.split_type+'_'+self.id[index]].items():
                            summary_commonsense += summ[self.supervision_relation][0].strip() +'. '

                with self.tokenizer.as_target_tokenizer():
                    encoded_extra_supervision = self.tokenizer(summary_commonsense,
                                                            padding='max_length',
                                                            truncation=True,
                                                            max_length=self.decoder_max_len,
                                                            return_tensors='pt')

                model_inputs['extra_labels'] = encoded_extra_supervision['input_ids'].squeeze(0)
                    
        return model_inputs


class TweetsummDataset_total:
    def __init__(self, encoder_max_len, decoder_max_len, tokenizer, subset_size, 
                 extra_context=False, extra_supervision=False, paracomet=False, 
                 relation="xReason",roberta=False,supervision_relation='isAfter', 
                 sentence_transformer=False, sentiment = False):
        self.train_dataset = TweetsummDataset(encoder_max_len, decoder_max_len, 'train',tokenizer,subset_size, extra_context,extra_supervision,paracomet=paracomet,relation=relation,roberta=roberta,supervision_relation=supervision_relation, sentence_transformer=sentence_transformer,  sentiment = sentiment)
        self.eval_dataset = TweetsummDataset(encoder_max_len, decoder_max_len, 'validation', tokenizer,subset_size, extra_context,extra_supervision,paracomet=paracomet,relation=relation,roberta=roberta,supervision_relation=supervision_relation, sentence_transformer=sentence_transformer,  sentiment = sentiment)
        self.test_dataset = TweetsummDataset(encoder_max_len, decoder_max_len, 'test', tokenizer,100, extra_context,extra_supervision,paracomet=paracomet,relation=relation,roberta=roberta,supervision_relation=supervision_relation, sentence_transformer=sentence_transformer,  sentiment = sentiment)
        print(self.train_dataset.data_len)
    def getTrainData(self):
        return self.train_dataset
    
    def getEvalData(self):
        return self.eval_dataset

    def getTestData(self):
        return self.test_dataset


class SamsumDataset_low(Dataset):
    def __init__(self, encoder_max_len, decoder_max_len, split_type, tokenizer, subset_size,
                extra_context=False, extra_supervision=False, paracomet=False,
                relation = "xReason", supervision_relation="isAfter", roberta=False, sentiment = False):

        self.encoder_max_len = encoder_max_len
        self.decoder_max_len = decoder_max_len
        self.split_type = split_type
        self.tokenizer = tokenizer
        self.subset_size = subset_size
        self.sentiment = sentiment
        self.extra_context=extra_context
        self.extra_supervision=extra_supervision
        ####### THIS WILL BE ALTERED IN THE FUTURE #######
        # self.relation = 'xReason'
        self.relation = relation
        self.paracomet = paracomet
        if self.paracomet and (self.relation[0] != "<"):
            self.relation = f"<|{self.relation}|>"
        
        self.supervision_relation = supervision_relation
        if self.paracomet and (self.supervision_relation[0] != "<"):
            self.supervision_relation = f"<|{self.supervision_relation}|>"

        self.roberta = roberta
        print(self.relation)
        ##################################################

        self.data = load_dataset('samsum',split=split_type)
        #total = [i for i in range(len(self.data))]
        #self.subset_size = subset_size#int(0.1*len(self.data))
        
        

        #low_res = random.sample(total,len(self.data)//10)
        #whole_dialogue = self.data['dialogue']
        #whole_summary = self.data['summary']
        #whole_id = self.data['id']
        subset_indices = random.sample(range(len(self.data)), int((self.subset_size)/100 * int(len(self.data))))
        self.data = self.data.select(subset_indices)
        #self.dialogue = [whole_dialogue[i] for i in low_res]
        #self.summary = [whole_summary[i] for i in low_res]
        #self.id = [whole_id[i] for i in low_res]

        self.dialogue = self.data['dialogue']
        self.summary = self.data['summary']
        self.id = self.data['id']

        self.nlp = spacy.load('en_core_web_sm')
        
        ###########################
        #   LOAD .json dataset    #
        ###########################
        if self.extra_context==True:
            if self.paracomet==False:
                #with open(os.path.join(DATA_DIR, f"preprocessed/samsum/comet_{self.split_type}.json")) as f:
                with open(f"../data/COMET_data/comet/dialogue/samsum/comet_{self.split_type}.json") as f:
                    self.dialogue_comet_inference = json.load(f)
                
                if self.roberta:
                    #with open(os.path.join(DATA_DIR, f"RobertaClassifier/samsum/roberta_classified_top1_{self.split_type}.json")) as f:
                    with open(f"../data/COMET_data/comet/dialogue/samsum/roberta_nli/roberta_classified_top1_{self.split_type}.json") as f: 
                        self.roberta_classified_z = json.load(f)
                    
            else:
                #with open(os.path.join(DATA_DIR,f"narrative_inference_demo/samsum_preprocess/collated/dialog_{self.split_type}_split5_collated.json")) as f:
                with open(f"../data/COMET_data/paracomet/dialogue/samsum/dialog_{self.split_type}_split5_collated.json") as f:
                    self.dialogue_comet_inference = json.load(f)
              
        
        if self.extra_supervision==True: # use commonsense w
            if self.split_type=='train':
                if self.paracomet==False: # plain COMET
                    #with open(os.path.join(DATA_DIR,"preprocessed/samsum/comet_train_w.json")) as f:
                    with open(f"../data/COMET_data/comet/summary/samsum/comet_train_w.json") as f:
                        self.summary_comet_inference = json.load(f)

                    if self.roberta:
                        with open(f"../data/COMET_data/comet/summary/samsum/roberta_nli/roberta_classified_top1_w.json") as f:
                        #with open(os.path.join(DATA_DIR, f"RobertaClassifier/samsum/roberta_classified_top1_w.json")) as f:
                            self.roberta_classified_w = json.load(f)
                else:
                    #with open(os.path.join(DATA_DIR,"narrative_inference_demo/samsum_preprocess/collated/summary_train_split5_collated.json")) as f:
                    with open(f"../data/COMET_data/paracomet/summary/samsum/summary_train_split5_collated.json") as f:
                      self.summary_comet_inference = json.load(f)
        
        self.data_len = len(self.data)


        # total = [i for i in range(self.data_len)]
        # self.low_res = random.sample(total,self.data_len//10)
        # print(self.low_res)


    def compute_best_relation(self, sentence, d: dict):
      #print(sentence)
      encoded_sentence = self.tokenizer(sentence,
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.encoder_max_len, 
                                            return_tensors='pt')
      commonsenseDict = {}
      commonsenseDict['HinderedBy'] = d['HinderedBy'][0]
      commonsenseDict['xWant'] = d['xWant'][0]
      commonsenseDict['xIntent'] = d['xIntent'][0]
      commonsenseDict['xNeed'] = d['xNeed'][0]
      commonsenseDict['xReason'] = d['xReason'][0]

      print(commonsenseDict)
        
      for k, v in commonsenseDict.items():
        encoded = self.tokenizer(v, padding='max_length', 
                                              truncation=True, 
                                              max_length=self.encoder_max_len, 
                                              return_tensors='pt')
        similarity = cosine_similarity(encoded_sentence['input_ids'], encoded['input_ids'])
        commonsenseDict[k] = similarity[0][0]
      
      print(commonsenseDict)  
      return max(commonsenseDict, key=commonsenseDict.get)





    def process_media_msg(self,sentence, person, commonsense):
        # print(person)
        if ('<file_photo>' in sentence) or ('<photo_file>' in sentence) or ('<file_picture>' in sentence):
            return "<I> " + person + " sent a photo. </I>" + '\n' 
        elif ('<video>' in sentence) or ('<file_video>' in sentence):
            return "<I> " + person + " sent a video. </I>" + '\n'
        elif '<file_gif>' in sentence:
            return "<I> " + person + " sent a file. </I>" + '\n'
        elif ('<file_other>' in sentence) or ('<file_others>' in sentence):
            return "<I> " + person + " sent a file. </I>" + '\n'
        elif ('<link>' in sentence) or ('<file_link>' in sentence):
            return "<I> " + person + " sent a link. </I>" + '\n'
        elif '<location>' in sentence:
            return "<I> " + person + " sent a location. </I>" + '\n'
        else:
            if commonsense.strip() != 'none':
                ## Try to ADD sentiment : Negative / positive
                if self.sentiment == True :
                    #sent = sentiment_analysis(sentence)[0]["label"]
                    return "<I> " + commonsense.strip() + "," + sent + ". </I>" + '\n'
                else : 
                    return "<I> " + commonsense.strip() + ". </I>" + '\n'
            else:
                return "" 


    def __len__(self):
        return self.data_len

    def __getitem__(self, index):
        if self.extra_context==False:
            #print("##################### changes in line 859 and 923: ask to professor. Bug? operation in line 784 does not work properly")
            encoded_dialogue = self.tokenizer(self.dialogue[index], 
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.encoder_max_len, 
                                            return_tensors='pt')
        else:
            if self.paracomet==False: # plain COMET
                try:
                    
                    dia = self.dialogue_comet_inference[self.id[index]]
                    #n = len(dia)
                    dialogue=""
                    for sent_idx, sent in enumerate(dia):
                        person = sent['speaker'].replace(": ","").replace(":","").strip()
                        sentence = sent['sentence'].strip()
                        #previous = dia[max(0,sent_idx - 10):min(sent_idx + 1, n]
                        if self.roberta:
                            commonsense = self.roberta_classified_z[self.id[index]][str(sent_idx)]["out"]
                            #print(f"Commonsense: {commonsense}")
                        else:
                            self.relation = self.compute_best_relation(sentence, sent)
                            print(f"Best relation: {self.relation}")
                            #print(f"Relation: {self.relation}")
                            commonsense = sent[self.relation][0].strip()
                            print(f"Commonsense: {commonsense}")

                        commonsense = commonsense.replace("PersonX","Person").replace("PersonY","Person")
                        dialogue += person + " said \"" + sentence + ".\"" + '\n'
                        if sent['speaker']+sentence != commonsense:
                            # print(self.process_media_msg(sentence, person, commonsense))
                            #dialogue += self.process_media_msg(sentence, person, commonsense, previous_uterances)

                            dialogue += self.process_media_msg(sentence, person, commonsense)
                except KeyError:
                    print("key error")
                    dialogue = self.dialogue[index]

                   
                        
            else: # use PARACOMETd
                try:
                    dia = self.dialogue_comet_inference[self.id[index]]
                    dialogue=""
                    #k = 0
                    for _,sent in dia.items():
                        sentence = sent['sentence'].strip()
                        #previous = dia[max(0,sent_idx - 10):min(sent_idx + 1, len(dia)]
                        person = sentence.split()[0]
                        commonsense = sent[self.relation][0].strip()

                        dialogue += sentence +'\n'

                        if sentence != commonsense:
                            dialogue += self.process_media_msg(sentence, person, commonsense)
                    #k+=1
                except KeyError: # when an error occurred while processing commonsense, just give plain utterance as output
                    print("key error")
                    # print(index)
                    # print(self.id[index])
                    # print(self.dialogue_comet_inference.keys())
                    dialogue = self.dialogue[index]
             

            encoded_dialogue = self.tokenizer(dialogue,
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.encoder_max_len, 
                                            return_tensors='pt')


        # (1, sequence_length)
        with self.tokenizer.as_target_tokenizer():
            encoded_summary = self.tokenizer(self.summary[index], 
                                            padding='max_length', 
                                            truncation=True, 
                                            max_length=self.decoder_max_len, 
                                            return_tensors='pt')
        
            
        
        model_inputs = encoded_dialogue
        model_inputs['input_ids'] = model_inputs['input_ids'].squeeze(0)
        model_inputs['attention_mask'] = model_inputs['attention_mask'].squeeze(0)
        model_inputs['labels'] = encoded_summary['input_ids'].squeeze(0)

        if self.extra_supervision==True:
            if self.split_type=='train':
                def split_sentences(text, speaker):
                    doc = self.nlp(text)
                    sents = [speaker.replace(":","") + ' said "' + sent.text + '"' for sent in doc.sents]
                    return sents

                if self.paracomet==False: # plain COMET
                    summary_commonsense = ""
                    if self.roberta:
                        for _, summ in self.roberta_classified_w[self.id[index]].items():
                            commonsense = summ["out"].strip() + ". "
                            commonsense = commonsense.replace("PersonX","Person").replace("PersonY","Person")
                            summary_commonsense += commonsense

                    else:
                        for summ in self.summary_comet_inference[self.id[index]]:
                            commonsense = summ[self.supervision_relation][0].strip() +'. '
                            commonsense = commonsense.replace("PersonX","Person").replace("PersonY","Person")
                            summary_commonsense += commonsense

                    with self.tokenizer.as_target_tokenizer():
                        encoded_extra_supervision = self.tokenizer(summary_commonsense,
                                                                padding='max_length',
                                                                truncation=True,
                                                                max_length=self.decoder_max_len,
                                                                return_tensors='pt')

                    model_inputs['extra_labels'] = encoded_extra_supervision['input_ids'].squeeze(0)
                else:
                    if index==6054:
                        summary_commonsense = "problem with presentation."
                    else:
                        summary_commonsense = ""
                        for _,summ in self.summary_comet_inference[self.id[index]].items():
                            try:
                                summary_commonsense += summ[self.supervision_relation][0].strip() +'. '
                            except KeyError:
                                print("key error in supervision")
                                summary_commonsense = ""

                    with self.tokenizer.as_target_tokenizer():
                        encoded_extra_supervision = self.tokenizer(summary_commonsense,
                                                                padding='max_length',
                                                                truncation=True,
                                                                max_length=self.decoder_max_len,
                                                                return_tensors='pt')

                    model_inputs['extra_labels'] = encoded_extra_supervision['input_ids'].squeeze(0)
                # print(summary_commonsense)
            
        return model_inputs

class SamsumDataset_low_total:
    def __init__(self, encoder_max_len, decoder_max_len, tokenizer, subset_size, extra_context=False, extra_supervision=False, paracomet=False,relation="xReason", supervision_relation='isAfter',roberta=False, sentiment = False):
        self.train_dataset = SamsumDataset_low(encoder_max_len, decoder_max_len, 'train',tokenizer,subset_size, extra_context=extra_context,extra_supervision=extra_supervision,paracomet=paracomet,relation=relation, supervision_relation=supervision_relation, roberta=roberta, sentiment = sentiment)
        self.eval_dataset = SamsumDataset_low(encoder_max_len, decoder_max_len, 'validation', tokenizer, subset_size, extra_context=extra_context,extra_supervision=extra_supervision,paracomet=paracomet,relation=relation, supervision_relation=supervision_relation, roberta=roberta,  sentiment = sentiment)
        self.test_dataset = SamsumDataset(encoder_max_len, decoder_max_len, 'test', tokenizer, extra_context=extra_context,extra_supervision=extra_supervision,paracomet=paracomet,relation=relation, supervision_relation=supervision_relation, roberta=roberta,  sentiment = sentiment)
    
    def getTrainData(self):
        return self.train_dataset
    
    def getEvalData(self):
        return self.eval_dataset

    def getTestData(self):
        return self.test_dataset
