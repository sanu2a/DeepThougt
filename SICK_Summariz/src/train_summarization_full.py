import os
os.environ['FOR_DISABLE_CONSOLE_CTRL_HANDLER'] = '1'

import sys
sys.path.append('../')
import argparse
import random
import json
import nltk
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader, SequentialSampler
from transformers import AutoTokenizer
from transformers import AutoConfig, AutoModelForSeq2SeqLM
from transformers import Seq2SeqTrainingArguments, Seq2SeqTrainer
from datasets import load_metric
#import wandb  #commented due to problems when using kaggle PaaS
from dataset import SamsumDataset_total, DialogsumDataset_total, TweetsummDataset_total
from models.bart import BartForConditionalGeneration_DualDecoder
from src.trainer import DualDecoderTrainer

from peft import get_peft_config, get_peft_model, LoraConfig, TaskType, PeftModel

# Set Argument Parser
parser = argparse.ArgumentParser()
# Training hyperparameters
parser.add_argument('--subset_size', type = int, default = 100) #choose the percentage of data you want to use
parser.add_argument('--epoch', type=int, default=20)
parser.add_argument('--train_batch_size', type=int, default=16)
#parser.add_argument('--display_step',type=int, default=14000)
parser.add_argument('--val_batch_size',type=int, default=4)
parser.add_argument('--test_batch_size',type=int,default=1)
# Model hyperparameters
parser.add_argument('--model_name',type=str, default='facebook/bart-large-xsum')
parser.add_argument('--lora_finetuning', type=bool,default=False)
parser.add_argument('--lora_r', type=int,default=16)
# Optimizer hyperparameters
parser.add_argument('--init_lr',type=float, default=3e-6)
parser.add_argument('--warm_up',type=int, default=600)
parser.add_argument('--weight_decay',type=float, default=1e-2)
parser.add_argument('--decay_epoch',type=int, default=0)
parser.add_argument('--adam_beta1',type=float, default=0.9)
parser.add_argument('--adam_beta2',type=float, default=0.999)
parser.add_argument('--adam_eps',type=float, default=1e-12)
parser.add_argument('--dropout_rate',type=float, default=0.1)
# Tokenizer hyperparameters
parser.add_argument('--encoder_max_len', type=int, default=1024)
parser.add_argument('--decoder_max_len', type=int, default=100)
parser.add_argument('--vocab_size',type=int, default=51201)
parser.add_argument('--eos_idx',type=int, default=51200)
parser.add_argument('--tokenizer_name',type=str, default='RobertaTokenizer')
# Checkpoint directory hyperparameters
parser.add_argument('--pretrained_weight_path',type=str, default='pretrained_weights')
parser.add_argument('--finetune_weight_path', type=str, default="./supervision_BART_weights_Samsum_5epoch")
parser.add_argument('--best_finetune_weight_path',type=str, default='supervision_final_BART_weights_Samsum_5epoch')
# Dataset hyperparameters
parser.add_argument('--dataset_name',type=str, default='samsum')
parser.add_argument('--use_paracomet',type=bool,default=False)
parser.add_argument('--use_roberta',type=bool,default=False)
parser.add_argument('--use_sentence_transformer',type=bool,default=False)
parser.add_argument('--dataset_directory',type=str, default='./data')
parser.add_argument('--test_output_file_name',type=str, default='samsum_context_trial2.txt')
parser.add_argument('--relation',type=str,default="xReason")
parser.add_argument('--supervision_relation',type=str,default='isAfter')
parser.add_argument('--emotion', type = bool, default = False) #set to True to use emotion-aware commonsense

args = parser.parse_args()


# Set GPU
print('######################################################################')
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print('Device:', device)
print('Current cuda device:', torch.cuda.current_device())
print('Count of using GPUs:', torch.cuda.device_count())
print(torch.cuda.get_device_name())
print('######################################################################')


# Start WANDB Log (Set Logging API)
#wandb.init(project="ICSK4AS", reinit=True, entity='icsk4as')


# Define Global Values
model_checkpoint_list = [
    "facebook/bart-large", 
    "facebook/bart-large-xsum",
    "google/pegasus-large",
    "google/peagsus-xsum",
    "google/t5-large-lm-adapt", 
    "google/t5-v1_1-large"
]
tokenizer_list = {
    "facebook/bart-large":"RobertaTokenizer",
    "facebook/bart-large-xsum":"RobertaTokenizer",
    "google/pegasus-large":"PegasusTokenizer",
    "google/peagsus-xsum":"PegasusTokenizer",
    "google/t5-large-lm-adapt":"T5Tokenizer", 
    "google/t5-v1_1-large":"T5Tokenizer"
}
max_len_list ={
    "facebook/bart-large":1024,
    "facebook/bart-large-xsum":1024,
    "google/pegasus-large":1024,
    "google/peagsus-xsum":512,
    "google/t5-large-lm-adapt":512, 
    "google/t5-v1_1-large":512
}
vocab_size_list={
    "facebook/bart-large":50265,
    "facebook/bart-large-xsum":50264,
    "google/pegasus-large":96103,
    "google/peagsus-xsum":96103,
    "google/t5-large-lm-adapt":32128, 
    "google/t5-v1_1-large":32128
}
#added new dataset
dataset_list = [
    "samsum","dialogsum", "tweetsumm"
]

#new strategy for commonsense selection, best_relation

relation_list_comet = [
  'best_relation', 'xNeed', 'HinderedBy', 'xWant',  'xReason', 'xIntent' 
]
relation_list_paracomet = [
  'best_relation', 'xIntent', 'xWant', 'xReact', 'xEffect', 'xAttr'
]


# Refine arguments based on global values
if args.model_name not in model_checkpoint_list:
    assert "Your Model checkpoint name is not valid"
args.tokenizer_name = tokenizer_list[args.model_name]
#args.max_len = max_len_list[args.model_name]
#args.max_len = 1024
args.vocab_size = vocab_size_list[args.model_name]
if args.dataset_name not in dataset_list:
    assert "Your Dataset name is not valid"


# Set metric
metric = load_metric("../utils/rouge.py")

# Load Tokenizer associated to the model
tokenizer = AutoTokenizer.from_pretrained(args.model_name)

# Add special token 
special_tokens_dict = {'additional_special_tokens':['<I>','</I>']}
tokenizer.add_special_tokens(special_tokens_dict)


# Set dataset

if args.dataset_name=='samsum':
    total_dataset = SamsumDataset_total(args.encoder_max_len,args.decoder_max_len,tokenizer,subset_size = args.subset_size, extra_context=True, extra_supervision = True, paracomet=args.use_paracomet,relation=args.relation,supervision_relation=args.supervision_relation,roberta=args.use_roberta, sentence_transformer=args.use_sentence_transformer,emotion = args.emotion)
    train_dataset = total_dataset.getTrainData()
    eval_dataset = total_dataset.getEvalData()
    test_dataset = total_dataset.getTestData()
elif args.dataset_name=='dialogsum':
    total_dataset = DialogsumDataset_total(args.encoder_max_len,args.decoder_max_len,tokenizer,subset_size = args.subset_size, extra_context=True, extra_supervision = True, paracomet=args.use_paracomet,relation=args.relation,supervision_relation=args.supervision_relation, sentence_transformer=args.use_sentence_transformer, roberta=args.use_roberta, emotion = args.emotion)
    train_dataset = total_dataset.getTrainData()
    eval_dataset = total_dataset.getEvalData()
    test_dataset = total_dataset.getTestData()
elif args.dataset_name=='tweetsumm':
    total_dataset = TweetsummDataset_total(args.encoder_max_len,args.decoder_max_len,tokenizer,subset_size = args.subset_size, extra_context=True, extra_supervision = True, paracomet=args.use_paracomet,relation=args.relation,supervision_relation=args.supervision_relation, sentence_transformer=args.use_sentence_transformer, roberta=args.use_roberta, emotion = args.emotion)
    train_dataset = total_dataset.getTrainData()
    eval_dataset = total_dataset.getEvalData()
    test_dataset = total_dataset.getTestData()

print('######################################################################')
print('Training Dataset Size is : ')
print(len(train_dataset))
print('Validation Dataset Size is : ')
print(len(eval_dataset))
print('Test Dataset Size is : ')
print(len(test_dataset))
print('######################################################################')


# Set metric
metric = load_metric("../utils/rouge.py")

# Load Tokenizer associated to the model
tokenizer = AutoTokenizer.from_pretrained(args.model_name)

# Add special token 
special_tokens_dict = {'additional_special_tokens':['<I>','</I>']}
tokenizer.add_special_tokens(special_tokens_dict)
# Loading checkpoint of model
config = AutoConfig.from_pretrained(args.model_name)
finetune_model = BartForConditionalGeneration_DualDecoder.from_pretrained(args.model_name)
finetune_model.resize_token_embeddings(len(tokenizer))
# Fine-tuning a subset of parameters instead of the full model. In this way it's more resource efficient and it's faster.
# The final results are comparable with the full training of the model. 
if args.lora_finetuning == True:
    peft_config = LoraConfig(
        task_type=TaskType.SEQ_2_SEQ_LM, inference_mode=False, r=args.lora_r, lora_alpha=32, lora_dropout=0.1
    )
    finetune_model = get_peft_model(finetune_model, peft_config) 
    
print('######################################################################')
print("Number of Model Parameters are : ",finetune_model.print_trainable_parameters() if args.lora_finetuning else finetune_model.num_parameters())
print('######################################################################')



# Set extra Configuration for Finetuning on Summarization Dataset
finetune_model.gradient_checkpointing_enable()
finetune_model = finetune_model.to(device)


# Set Training Arguments (& Connect to WANDB)
finetune_args = Seq2SeqTrainingArguments(
    output_dir = args.finetune_weight_path,
    overwrite_output_dir = True,
    do_train=True,
    do_eval=False,
    do_predict=False,
    #evaluation_strategy='epoch',
    #eval_steps=args.display_step,
    per_device_train_batch_size = args.train_batch_size,
    #per_device_eval_batch_size = args.val_batch_size,
    learning_rate=args.init_lr,
    weight_decay=args.weight_decay,
    adam_beta1=args.adam_beta1,
    adam_beta2=args.adam_beta2,
    adam_epsilon=args.adam_eps,
    num_train_epochs=args.epoch,
    max_grad_norm=0.1,
    #label_smoothing_factor=0.1,
    gradient_accumulation_steps=2,
    gradient_checkpointing=True,
    # max_steps= ,
    lr_scheduler_type='polynomial',
    #warmup_ratio= ,
    warmup_steps= args.warm_up,
    logging_strategy="epoch",
    #logging_steps=args.display_step,
    save_strategy= "epoch",
    #save_steps=args.display_step,
    save_total_limit=1,
    fp16=True,
    seed = 516,
    #load_best_model_at_end=True,
    #predict_with_generate=True,
    #prediction_loss_only=False,
    #generation_max_length=100,
    #generation_num_beams=5,
    #metric_for_best_model='eval_rouge2',
    greater_is_better=True,
    report_to = 'none',
    disable_tqdm=False
)

def compute_metrics(eval_pred):
    predictions, labels = eval_pred
    decoded_preds = tokenizer.batch_decode(predictions, skip_special_tokens=True)
    # Replace -100 in the labels as we can't decode them.
    labels = np.where(labels != -100, labels, tokenizer.pad_token_id)
    decoded_labels = tokenizer.batch_decode(labels, skip_special_tokens=True)
    
    # Rouge expects a newline after each sentence
    decoded_preds = ["\n".join(nltk.sent_tokenize(pred.strip())) for pred in decoded_preds]
    decoded_labels = ["\n".join(nltk.sent_tokenize(label.strip())) for label in decoded_labels]
    
    result = metric.compute(predictions=decoded_preds, references=decoded_labels, use_stemmer=True)
    # Extract a few results
    result = {key: value.mid.fmeasure * 100 for key, value in result.items()}
    
    # Add mean generated length
    prediction_lens = [np.count_nonzero(pred != tokenizer.pad_token_id) for pred in predictions]
    result["gen_len"] = np.mean(prediction_lens)
    
    return {k: round(v, 4) for k, v in result.items()}

finetune_trainer = DualDecoderTrainer(
    model = finetune_model,
    args = finetune_args,
    train_dataset = train_dataset,
    #eval_dataset = eval_dataset,
    tokenizer = tokenizer,
    #compute_metrics=compute_metrics
)


# Run Training (Finetuning)
finetune_trainer.train()

# We merge the the parameters just trained with the original model to create a new complete model instead of a LoRa checkpoint for compatibility purposes
if args.lora_finetuning:
    finetune_trainer.model = finetune_trainer.model.merge_and_unload()

# Save final weights
finetune_trainer.save_model(args.best_finetune_weight_path)

"""
# Run Evaluation on Test Data
results = finetune_trainer.predict(
    test_dataset=test_dataset,
    max_length= 60,
    num_beams = 5   #1,3,5,10
)
predictions, labels, metrics = results
print('######################################################################')
print("Final Rouge Results are : ",metrics)
print('######################################################################')


# Write evaluation predictions on txt file
decoded_preds = tokenizer.batch_decode(predictions, skip_special_tokens=True)
    # Replace -100 in the labels as we can't decode them.
labels = np.where(labels != -100, labels, tokenizer.pad_token_id)
decoded_labels = tokenizer.batch_decode(labels, skip_special_tokens=True)
    
    # Rouge expects a newline after e ach sentence
decoded_preds = [" ".join(nltk.sent_tokenize(pred.strip())) for pred in decoded_preds]
decoded_labels = [" ".join(nltk.sent_tokenize(label.strip())) for label in decoded_labels]


# output summaries on test set
with open(args.test_output_file_name,"w") as f: 
    f.write(metrics)
    for i in decoded_preds:
        f.write(i.replace("\n","")+"\n")
"""
# END WANDB log
#wandb.finish()
