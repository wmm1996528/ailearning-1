# -*- coding: utf-8 -*-
"""NER_Bert.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/13rfbXaTbKpzF4VEiN2kkRPVnVoshoSuy

利用Bert解决NER问题

dataset: https://www.kaggle.com/abhinavwalia95/entity-annotated-corpus/download
"""

# !pip install pytorch-pretrained-bert==0.4.0

"""载入数据"""

import pandas as pd
import numpy as np
# from tqdm import tqdm, trange

# from google.colab import files
# data = files.upload()

"""展示数据最后几行"""

data = pd.read_csv("ner_dataset.csv", encoding="latin1").fillna(method="ffill")
data.tail(10)

"""构建SentenceGetter"""

class SentenceGetter(object):
    
    def __init__(self, data):
      self.n_sent = 1
      self.data = data
      self.empty = False
      agg_func = lambda s: [(w, p, t) for w, p, t in zip(s["Word"].values.tolist(),s["POS"].values.tolist(),s["Tag"].values.tolist())]
      self.grouped = self.data.groupby("Sentence #").apply(agg_func)
      self.sentences = [s for s in self.grouped]
    
    def get_next(self):
      try:
        s = self.grouped["Sentence: {}".format(self.n_sent)]
        self.n_sent += 1
        return s
      except:
        self.empty = True
        return None

getter = SentenceGetter(data)

sentences = [" ".join([s[0] for s in sent]) for sent in getter.sentences]
# sentences[0]

labels = [[s[2] for s in sent] for sent in getter.sentences]
print(labels[0])

"""构建tag词典"""

tags_vals = list(set(data["Tag"].values))
tag2idx = {t: i for i, t in enumerate(tags_vals)}

"""导入相关库"""

# !pip install pytorch_pretrained_bert

import torch
from torch.optim import Adam
from torch.utils.data import TensorDataset, DataLoader, RandomSampler, SequentialSampler
from keras.preprocessing.sequence import pad_sequences
from sklearn.model_selection import train_test_split
from pytorch_pretrained_bert import BertTokenizer, BertConfig
from pytorch_pretrained_bert import BertForTokenClassification, BertAdam

"""设置基本参数"""

max_len = 60
batch_size = 32

"""设置device"""

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
n_gpu = torch.cuda.device_count()
torch.cuda.get_device_name(0)

"""tokenize处理"""

tokenizer = BertTokenizer.from_pretrained('bert-base-uncased', do_lower_case=True)
tokenized_texts = [tokenizer.tokenize(sent) for sent in sentences]
print(tokenized_texts[0])

"""将输入转化为id 并且 截长补短"""

input_ids = pad_sequences([tokenizer.convert_tokens_to_ids(txt) for txt in tokenized_texts],
                          maxlen=max_len, dtype="long", truncating="post", padding="post")
print(input_ids[0])

tags = pad_sequences([[tag2idx.get(l) for l in lab] for lab in labels],
                     maxlen=max_len, value=tag2idx["O"], padding="post",
                     dtype="long", truncating="post")
print(tags[0])

"""准备mask_attention"""

attention_masks = [[float(i>0) for i in ii] for ii in input_ids]
print(attention_masks[0])

"""将数据进行划分"""

tr_inputs, val_inputs, tr_tags, val_tags = train_test_split(input_ids, tags, random_state=2019, test_size=0.1)
tr_masks, val_masks, _, _ = train_test_split(attention_masks, input_ids, random_state=2019, test_size=0.1)

"""将数据转化为tensor的形式"""

tr_inputs = torch.tensor(tr_inputs)
val_inputs = torch.tensor(val_inputs)
tr_tags = torch.tensor(tr_tags)
val_tags = torch.tensor(val_tags)
tr_masks = torch.tensor(tr_masks)
val_masks = torch.tensor(val_masks)

"""定义dataloader,在训练阶段shuffle数据，预测阶段不需要shuffle"""

train_data = TensorDataset(tr_inputs, tr_masks, tr_tags)
train_sampler = RandomSampler(train_data)
train_dataloader = DataLoader(train_data, sampler=train_sampler, batch_size=batch_size)

valid_data = TensorDataset(val_inputs, val_masks, val_tags)
valid_sampler = SequentialSampler(valid_data)
valid_dataloader = DataLoader(valid_data, sampler=valid_sampler, batch_size=batch_size)

"""**开始训练过程**"""

model = BertForTokenClassification.from_pretrained("bert-base-uncased", num_labels=len(tag2idx))

model.cuda()

"""定义optimizer(分为是否调整全部参数两种情况)"""

FULL_FINETUNING = True
if FULL_FINETUNING:
    param_optimizer = list(model.named_parameters())
    no_decay = ['bias', 'gamma', 'beta']
    optimizer_grouped_parameters = [
        {'params': [p for n, p in param_optimizer if not any(nd in n for nd in no_decay)],
         'weight_decay_rate': 0.01},
        {'params': [p for n, p in param_optimizer if any(nd in n for nd in no_decay)],
         'weight_decay_rate': 0.0}
    ]
else:
    param_optimizer = list(model.classifier.named_parameters())
    optimizer_grouped_parameters = [{"params": [p for n, p in param_optimizer]}]
optimizer = BertAdam(optimizer_grouped_parameters, lr=3e-5)

"""定义评估accuracy的函数

f1: https://blog.csdn.net/qq_37466121/article/details/87719044
"""

# !pip install seqeval
from seqeval.metrics import f1_score

def flat_accuracy(preds, labels):
    pred_flat = np.argmax(preds, axis=2).flatten()
    labels_flat = labels.flatten()
    return np.sum(pred_flat == labels_flat) / len(labels_flat)

"""开始微调过程，建议4个左右epochs"""

epochs = 5
max_grad_norm = 1.0

for _ in range(epochs, desc="Epoch"): # trange有可视化功能
    # 训练过程
    model.train()
    tr_loss = 0
    nb_tr_steps = 0
    for step, batch in enumerate(train_dataloader):
        # 将batch设置为gpu模式
        batch = tuple(t.to(device) for t in batch)
        b_input_ids, b_input_mask, b_labels = batch
        # 前向过程
        loss = model(b_input_ids, token_type_ids=None,
                     attention_mask=b_input_mask, labels=b_labels)
        # 后向过程
        loss.backward()
        # 损失
        tr_loss += loss.item()
        nb_tr_steps += 1
        # 梯度裁剪
        torch.nn.utils.clip_grad_norm_(parameters=model.parameters(), max_norm=max_grad_norm)
        # 更新参数
        optimizer.step()
        model.zero_grad()
    #打印每个epoch的损失
    print("Train loss: {}".format(tr_loss/nb_tr_steps))
    # 验证过程
    model.eval()
    eval_loss, eval_accuracy = 0, 0
    nb_eval_steps = 0
    predictions , true_labels = [], []
    for batch in valid_dataloader:
        batch = tuple(t.to(device) for t in batch)
        b_input_ids, b_input_mask, b_labels = batch

        with torch.no_grad():
            tmp_eval_loss = model(b_input_ids, token_type_ids=None,
                                  attention_mask=b_input_mask, labels=b_labels)
            logits = model(b_input_ids, token_type_ids=None,
                           attention_mask=b_input_mask)
        logits = logits.detach().cpu().numpy()#detach的方法，将variable参数从网络中隔离开，不参与参数更新
        label_ids = b_labels.to('cpu').numpy()

        # print("label_ids", label_ids)
        # print("np.argmax(logits, axis=2)", np.argmax(logits, axis=2))

        predictions.extend([list(p) for p in np.argmax(logits, axis=2)])
        true_labels.append(label_ids)
        # 计算accuracy 和 loss
        tmp_eval_accuracy = flat_accuracy(logits, label_ids)

        eval_loss += tmp_eval_loss.mean().item()
        eval_accuracy += tmp_eval_accuracy
        nb_eval_steps += 1
    # 打印信息
    print("Validation loss: {}".format(eval_loss/nb_eval_steps))
    print("Validation Accuracy: {}".format(eval_accuracy/nb_eval_steps))
    pred_tags = [tags_vals[p_i] for p in predictions for p_i in p]
    valid_tags = [tags_vals[l_ii] for l in true_labels for l_i in l for l_ii in l_i]
    print("F1-Score: {}".format(f1_score(pred_tags, valid_tags)))#传入的是具体的tag

"""附：pytorch中各类数据的转换

*   Numpy to tensor: tensor_data_cpu = torch.from_numpy(np_data)
*   Cpu tensor to cuda: tensor_data_cuda= tensor_data_cpu.cuda()
*   Cuda data to Variable: tensor_data_cuda_var=Variable(tensor_data_cuda)
*   cuda Tensor to numpy: np_data=tensor_data_cuda.cpu().numpy()
*   cuda Variable to numpy: np_data=tensor_data_cuda_var.detach().cpu().numpy()
"""