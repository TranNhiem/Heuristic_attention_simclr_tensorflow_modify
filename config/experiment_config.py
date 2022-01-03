from config.absl_mock import Mock_Flag
from config.config import read_cfg_base

def read_cfg(mod="non_contrastive"):
    read_cfg_base(mod)
    flag = Mock_Flag()
    FLAGS = flag.FLAGS

    FLAGS.wandb_project_name = "heuristic_attention_representation_learning_Paper"
    FLAGS.wandb_run_name = "MNC_(7_7_2048)_100epoch_alpha_schedule_symloss"
    FLAGS.wandb_mod = "run"

    FLAGS.Middle_layer_output = None
    FLAGS.original_loss_stop_gradient = False
    FLAGS.Encoder_block_strides = {'1':2,'2':1,'3':2,'4':2,'5':2}
    FLAGS.Encoder_block_channel_output = {'1':1,'2':1,'3':1,'4':1,'5':1}
    
    FLAGS.loss_type ="symmetrized"# asymmetrized (2 only options)
    
    FLAGS.base_lr = 0.5

    FLAGS.non_contrast_binary_loss = "sum_symetrize_l2_loss_object_backg"
    FLAGS.alpha = 1
    FLAGS.weighted_loss = 0.5
    FLAGS.resnet_depth = 50
    FLAGS.train_epochs = 100
    FLAGS.num_classes = 1000

    FLAGS.train_batch_size = 128
    FLAGS.val_batch_size = 128
    FLAGS.model_dir = "/data1/share/resnet_byol/restnet50/Baseline_(7_7_2048)_200epoch/"
    #FLAGS.train_mode = "finetune"




