import os
import torch
from torch import nn
import pandas as pd

from crnn_dataset import get_split, TRDataset
from crnn_model import CRNN
from crnn_decoder import ctc_decode
from crnn_evaluate import evaluate

import argparse

def get_input_args():
    """
    Get command-line arguments using argparse.

    Returns:
        argparse.Namespace: Parsed arguments.
    """
    parser = argparse.ArgumentParser(description="YOLOv8 Dataset Generator")
    parser.add_argument("--cp_path", type=str, default=None, help="Configuration  checkpoint path.")
    parser.add_argument("--epochs", type=int, default=10, help="Number of training loop epochs.")
    parser.add_argument("--lr", type=float, default=0.0005, help="Training initial learning rate.")
    parser.add_argument("--batch_size", type=int, default=64, help="Number of samples per batch.")
    parser.add_argument("--show_interval", type=int, default=100, help="Interval of training steps to show.")
    return parser.parse_args()

def train_batch(crnn, data, optimizer, criterion, device):
    crnn.train()
    images, targets, target_lengths = [d.to(device) for d in data]

    logits = crnn(images)
    log_probs = torch.nn.functional.log_softmax(logits, dim=2)

    batch_size = images.size(0)
    input_lengths = torch.LongTensor([logits.size(0)] * batch_size)
    target_lengths = torch.flatten(target_lengths)

    loss = criterion(log_probs, targets, input_lengths, target_lengths)

    optimizer.zero_grad()
    loss.backward()
    torch.nn.utils.clip_grad_norm_(crnn.parameters(), 5) # gradient clipping with 5
    optimizer.step()
    return loss.item()

def main():
    args = get_input_args()
    
    reload_checkpoint = args.cp_path
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    
    if reload_checkpoint:
        config = torch.load(reload_checkpoint, map_location=device)
    else :
        print("No checkpoint found, using default configuration.")
        config = {
            'state_dict' : None,
            'img_height' : 32,
            'img_width' : 100,
            'batch_size' : 64,
            'root_dir' : "datasets/TR_100k",
            'labels' : "labels.csv",
            'splits' : [0.98,0.01,0.01],
            'map_to_seq' : 64,
            'rnn_hidden' : 256
        }
        
    config['batch_size'] = args.batch_size
    
    train_loader, val_loader, test_loader = get_split(root_dir=config['root_dir'],
                                                      labels=config['labels'],
                                                      img_width=config['img_width'],
                                                      img_height=config['img_height'],
                                                      batch_size=config['batch_size'],
                                                      splits=config['splits'])
    
    num_class = len(TRDataset.LABEL2CHAR) + 1
    
    crnn = CRNN(1, config['img_height'], config['img_width'], num_class,
                map_to_seq=config['map_to_seq'],
                rnn_hidden=config['rnn_hidden'])

    if config['state_dict']:
        crnn.load_state_dict(config['state_dict'])

    crnn.to(device)
    
    criterion = nn.CTCLoss(reduction='sum', zero_infinity=True)
    optimizer = torch.optim.Adam(crnn.parameters(), lr=args.lr)
    
    epochs = args.epochs
    show_interval = args.show_interval
    
    print(f"Training [{config['root_dir']}] using {device} for {epochs} epochs")
    
    train_losses = []
    val_losses = []
    val_accs = []
    for epoch in range(1,epochs+1):
        print(f'EPOCH [{epoch}/{epochs}]')
        run_train_loss = 0.
        run_train_count = 0
        
        step = 1
        for train_data in train_loader:
            loss = train_batch(crnn, train_data, optimizer, criterion, device)
            train_size = train_data[0].size(0)
            run_train_loss += loss
            run_train_count += train_size
            if step%show_interval == 0:
                print(f'Running Train Loss [{step}/{len(train_loader)}] : {run_train_loss/run_train_count :.2f}')
            
            step += 1
        
        train_loss = loss / train_size
        eval = evaluate(crnn, val_loader, criterion)
        
        print(f"EPOCH [{epoch}/{epochs}] => Train Loss : {train_loss:.4f} | Val Loss : {eval['loss']:.4f}, Val Acc: { eval['acc']}")
        train_losses.append(train_loss)
        val_losses.append(eval['loss'])
        val_accs.append(eval['acc'])

    print('[Evaluation]')
    final_eval = evaluate(crnn, val_loader, criterion)
    print(f"Val Loss : {final_eval['loss']:.4f}, Val Acc: {final_eval['acc']}")
    
    config['state_dict'] = crnn.state_dict()
    
    df = pd.DataFrame({
        'epoch': range(1, epochs + 1),
        'train_loss': train_losses,
        'val_loss': val_losses,
        'val_accuracy': val_accs
    })
    
    save_dir = os.path.join('runs', 'crnn_train')
    os.makedirs(save_dir, exist_ok=True)

    save_path = os.path.join(save_dir, 'train')
    i = 1
    while os.path.exists(save_path):
        save_path = os.path.join(save_dir, f'train{i}')
        i += 1
    
    os.makedirs(save_path, exist_ok=True)
        
    df.to_csv(os.path.join(save_path,'results.csv'), index = False)
    torch.save(config,os.path.join(save_path,'train_config.pt'))
    print(f'Results saved at {save_path}')
    
if __name__ == "__main__":
    main()   


