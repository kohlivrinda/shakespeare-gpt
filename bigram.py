"""
Original file is located at
    https://colab.research.google.com/drive/1y4HgNGaHCzosPujg27izdilTWU7WDmNn
"""
import torch 
import torch.nn as nn
from torch.nn import functional as F

#hyperparameters
block_size = 8
batch_size=32
max_iters=5000
eval_interval=300
learning_rate=1e-3
device = 'cuda' if torch.cuda.is_available() else 'cpu'
eval_iters=200
n_embd=32
#------------------

torch.manual_seed(1337)
 
#wget https://raw.githubusercontent.com/karpathy/char-rnn/master/data/tinyshakespeare/input.txt
with open('input.txt', 'r', encoding='utf-8') as f:
  text=f.read()

#unique characters that occur in the dataset text
chars=sorted(list(set(text)))
vocab_size=len(chars)

#create a mapping from characters to integers
#this is a (very rudimentary) tokenizer for our transformer
#since this project will be a character-level language model, the encoding is done character-wise too.
stoi= { ch: i for i,ch in enumerate(chars) }
itos= { i: ch for i,ch in enumerate(chars) }
encode= lambda s: [stoi[c] for c in s] #string to list of integers
decode = lambda l: ''.join([itos[i] for i in l]) #list of integers to string


#test-train(validation) split
data=torch.tensor(encode(text), dtype=torch.long)
n=int(0.9*len(data))
train_data=data[:n]
val_data=data[n:]

#data loading
def get_batch(split):
  ''' Generate a batch of data with inputs x and targets y '''
  data=train_data if split == 'train' else val_data
  ix = torch.randint(len(data) - block_size, (batch_size,)) 
  x=torch.stack([data[i:i+block_size] for i in ix])
  y=torch.stack([data[i+1:i+block_size+1] for i in ix])
  x,y = x.to(device), y.to(device)
  return x, y


@torch.no_grad()
def estimate_loss():
  out={}
  model.eval()
  for split in ['train', 'val']:
    losses=torch.zeros(eval_iters)
    for k in range(eval_iters):
      X,Y =get_batch(split)
      logits, loss=model(X,Y)
      losses[k]=loss.item()
    out[split]=losses.mean() #avg loss
  model.train()
  return out

print('----')

class Head(nn.Module):
  ''' one head of self attention '''
  def __init__(self, head_size):
    super().__init__()
    self.key=nn.Linear(n_embd, head_size, bias=False)
    self.query=nn.Linear(n_embd, head_size, bias=False)
    self.value =nn.Linear(n_embd, head_size, bias=False)
    self.register_buffer('tril', torch.tril(torch.ones(block_size, block_size)))
    
  def forward(self, x):
    B,T,C=x.shape 
    k=self.key(x) # B,T,C
    q=self.query(x) #B, T,C
    
    #here, we are essentially defining a decoder block
    #computing attention scores
    wei=q@k.transpose(-2, -1) *C**-0.5 #(B,T,C) @ (B,C,T) --> (B,T,T) 
    #formula used above, the root divide done to keep things scaled
    wei=wei.masked_fill(self.tril[:T, :T]==0, float('-inf')) # (B,T,T)
    wei=F.softmax(wei, dim=-1)
    
    #weighted aggregation of the vals
    v=self.value(x)
    out=wei @ v # BTT @ BTC ---> BTC
    return out

class MultiHeadAttention(nn.Module):
  """ multiple heads of sekf-attention in parallel """
  def __init__(self, num_heads, head_size):
    super().__init__()
    self.heads=nn.ModuleList([Head(head_size) for _ in range(num_heads)])
    
  def forward(self, x):
    return torch.cat([h(x) for h in self.heads], dim=-1) #dim -1 means Channel dimension
  
  
#simple bigram model
class BigramLanguageModel(nn.Module):

  def __init__(self, vocab_size):
    super().__init__()
    self.token_embedding_table=nn.Embedding(vocab_size, n_embd) #create a CxC embedding table
    self.position_embedding_table=nn.Embedding(block_size, n_embd)
    self.sa_heads=MultiHeadAttention(4,n_embd//4)
    self.lm_head=nn.Linear(n_embd, vocab_size) #language model head 
    
  def forward(self, idx, targets=None):
    B,T=idx.shape
    
    #idx and targets are (B,T) tensors
    tok_emb=self.token_embedding_table(idx) #(B,T,C tensor (batch x time x channel, here C is the vocab_size ))
    pos_emb=self.position_embedding_table(torch.arange(T, device=device)) #(T,C)
    x=tok_emb+pos_emb  
    x=self.sa_heads(x) #applying one head of self attention
    logits = self.lm_head(x) #(B, T, vocab_size )
    if targets is None:
      loss = None
    else:
      B,T,C = logits.shape
      logits=logits.view(B*T, C) #reshaping because of the way cross_entropy takes parameters.
      targets=targets.view(B*T)
      loss=F.cross_entropy(logits, targets)

    return logits, loss

  def generate(self, idx, max_new_tokens):
    ''' take B*T and make it into a B*T+n '''  
    for _ in range(max_new_tokens):
      #crop idx to the get the last block_size tokens, else positional embedding table will run out of scope, 
      idx_cond=idx[:, -block_size:]
      # get preds
      logits,loss=self(idx_cond)
      # focus on last time step since it will have two dims
      logits=logits[:, -1, :] #becomes (B,C)
      # apply softmax to get probabilities
      probs=F.softmax(logits, dim=-1) # (B,C)
      # sample from dist
      idx_next=torch.multinomial(probs, num_samples=1) # (B,1)
      # append sampled index to the running sequence
      idx=torch.cat((idx, idx_next), dim=1) #(B, T+1)
    return idx
    
model=BigramLanguageModel(vocab_size)
m=model.to(device)

#create a PyTorch optimizer
optimizer=torch.optim.AdamW(m.parameters(), lr=1e-3)

#train loop
for iter in range(max_iters):
  
  if iter % eval_interval==0:
    losses=estimate_loss()
    print(f"step{iter}: train loss {losses['train']:.4f}, val loss{losses['val']:.4f}")

  #sample a batch of data
  xb, yb=get_batch('train')
  
  #evaluate loss
  logits, loss=m(xb,yb)
  optimizer.zero_grad(set_to_none=True)
  loss.backward()
  optimizer.step()

#generating from the model
context=torch.zeros((1,1), dtype=torch.long, device=device)
print(decode(m.generate(context, max_new_tokens=500)[0].tolist()))

