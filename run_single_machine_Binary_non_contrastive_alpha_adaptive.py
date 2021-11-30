import os
import json
import math
import wandb
import random
from absl import flags
from absl import logging
from absl import app

import tensorflow as tf
from learning_rate_optimizer import WarmUpAndCosineDecay
import metrics
from helper_functions import *
from byol_simclr_imagenet_data_harry import imagenet_dataset_single_machine
from self_supervised_losses import byol_symetrize_loss, symetrize_l2_loss_object_level_whole_image, sum_symetrize_l2_loss_object_backg
import model_for_non_contrastive_framework as all_model
import objective as obj_lib
from imutils import paths
from wandb.keras import WandbCallback
from config import config_v0

# Setting GPU
gpus = tf.config.experimental.list_physical_devices('GPU')
if gpus:
    try:
        for gpu in gpus:
            tf.config.experimental.set_memory_growth(gpu, True)
        tf.config.experimental.set_visible_devices(gpus[0:8], 'GPU')
        logical_gpus = tf.config.experimental.list_logical_devices('GPU')
        print(len(gpus), "Physical GPUs,", len(logical_gpus), "Logical GPU")
    except RuntimeError as e:
        print(e)

FLAGS = flags.FLAGS
# ------------------------------------------
# General Define
# ------------------------------------------


flags.DEFINE_integer(
    'IMG_height', 224,
    'image height.')

flags.DEFINE_integer(
    'IMG_width', 224,
    'image width.')

flags.DEFINE_float(
    'LARGE_NUM', 1e9,
    'LARGE_NUM to multiply with Logit.')

flags.DEFINE_integer(
    'image_size', 224,
    'image size.')

flags.DEFINE_integer(
    'SEED', 26,
    'random seed use for shuffle data Generate two same image ds_one & ds_two')

flags.DEFINE_integer(
    'SEED_data_split', 100,
    'random seed for spliting data the same for all the run with the same validation dataset.')

flags.DEFINE_integer(
    'train_batch_size', 200,
    'Train batch_size .')

flags.DEFINE_integer(
    'val_batch_size', 200,
    'Validaion_Batch_size.')

flags.DEFINE_integer(
    'train_epochs', 50,
    'Number of epochs to train for.')

flags.DEFINE_integer(
    'num_classes', 200,
    'Number of class in training data.')


flags.DEFINE_string(
    #'train_path', "/mnt/sharefolder/Datasets/SSL_dataset/ImageNet/1K_New/ILSVRC2012_img_train",
    'train_path', '/data1/share/1K_New/train/',
    'Train dataset path.')

flags.DEFINE_string(
    # 'val_path',"/mnt/sharefolder/Datasets/SSL_dataset/ImageNet/1K_New/val",
    'val_path', "/data1/share/1K_New/val/",
    'Validaion dataset path.')

# Mask_folder should locate in location and same level of train folder
flags.DEFINE_string(
    'mask_path', "train_binary_mask_by_USS",
    'Mask path.')

flags.DEFINE_string(
    'train_label', "image_net_1k_lable.txt",
    'train_label.')

flags.DEFINE_string(
    'val_label', "ILSVRC2012_validation_ground_truth.txt",
    'val_label.')
# ------------------------------------------
# Define for Linear Evaluation
# ------------------------------------------
flags.DEFINE_enum(
    'linear_evaluate', 'standard', ['standard', 'randaug', 'cropping_randaug'],
    'How to scale the learning rate as a function of batch size.')

flags.DEFINE_integer(
    'eval_steps', 0,
    'Number of steps to eval for. If not provided, evals over entire dataset.')
# Configure RandAugment for validation dataset augmentation transform

flags.DEFINE_float(
    'randaug_transform', 1,
    'Number of augmentation transformations.')

flags.DEFINE_float(
    'randaug_magnitude', 7,
    'Number of augmentation transformations.')

# ----------------------------------------------------------
# Define for Learning Rate Optimizer + Training Strategy
# ----------------------------------------------------------

# Learning Rate Scheudle

flags.DEFINE_float(
    'base_lr', 0.5,
    'Initial learning rate per batch size of 256.')
print("use high learning rate")
flags.DEFINE_integer(
    'warmup_epochs', 10,  # Configure BYOL and SimCLR
    'warmup epoch steps for Cosine Decay learning rate schedule.')

flags.DEFINE_enum(
    'lr_rate_scaling', 'linear', ['linear', 'sqrt', 'no_scale', ],
    'How to scale the learning rate as a function of batch size.')

# Optimizer
# Same the Original SimClRV2 training Configure
'''ATTENTION'''
flags.DEFINE_enum(
    # if Change the Optimizer please change --
    'optimizer', 'LARSW', ['Adam', 'SGD', 'LARS', 'AdamW', 'SGDW', 'LARSW',
                           'AdamGC', 'SGDGC', 'LARSGC', 'AdamW_GC', 'SGDW_GC', 'LARSW_GC'],
    'How to scale the learning rate as a function of batch size.')

flags.DEFINE_enum(
    # Same the Original SimClRV2 training Configure
    # 1. original for ['Adam', 'SGD', 'LARS']
    # 2.optimizer_weight_decay for ['AdamW', 'SGDW', 'LARSW']
    # 3. optimizer_GD fir  ['AdamGC', 'SGDGC', 'LARSGC']
    # 4. optimizer_W_GD for ['AdamW_GC', 'SGDW_GC', 'LARSW_GC']

    'optimizer_type', 'optimizer_weight_decay', [
        'original', 'optimizer_weight_decay', 'optimizer_GD', 'optimizer_W_GD'],
    'Optimizer type corresponding to Configure of optimizer')

flags.DEFINE_float(
    'momentum', 0.9,
    'Momentum parameter.')

flags.DEFINE_float('weight_decay', 1e-6, 'Amount of weight decay to use.')

# ----------------------------------------------------------------------
# Configure for Encoder - Projection Head, Linear Evaluation Architecture
# ----------------------------------------------------------------------

# Encoder Configure

flags.DEFINE_boolean(
    'global_bn', True,
    'Whether to aggregate BN statistics across distributed cores.')

flags.DEFINE_float(
    'batch_norm_decay', 0.9,  # Checkout BN decay concept
    'Batch norm decay parameter.')

flags.DEFINE_integer(
    'width_multiplier', 1,
    'Multiplier to change width of network.')

flags.DEFINE_integer(
    'resnet_depth', 50,
    'Depth of ResNet.')

flags.DEFINE_float(
    'sk_ratio', 0.,
    'If it is bigger than 0, it will enable SK. Recommendation: 0.0625.')

flags.DEFINE_float(
    'se_ratio', 0.,
    'If it is bigger than 0, it will enable SE.')

# Projection Head

flags.DEFINE_enum(
    'proj_head_mode', 'nonlinear', ['none', 'linear', 'nonlinear'],
    'How the head projection is done.')

# Projection & Prediction head  (Consideration the project out dim smaller than Represenation)

flags.DEFINE_integer(
    'proj_out_dim', 512,
    'Number of head projection dimension.')

flags.DEFINE_integer(
    'prediction_out_dim', 512,
    'Number of head projection dimension.')

flags.DEFINE_boolean(
    'reduce_linear_dimention', True,  # Consider use it when Project head layers > 2
    'Reduce the parameter of Projection in middel layers.')

flags.DEFINE_integer(
    'up_scale', 4096,  # scaling the Encoder output 2048 --> 4096
    'Upscale the Dense Unit of Non-Contrastive Framework')

flags.DEFINE_boolean(
    'non_contrastive', True,  # Consider use it when Project head layers > 2
    'Using for upscaling the first layers of MLP == upscale value')

flags.DEFINE_integer(
    'num_proj_layers', 3,
    'Number of non-linear head layers.')

flags.DEFINE_integer(
    'ft_proj_selector', 0,
    'Which layer of the projection head to use during fine-tuning. '
    '0 means no projection head, and -1 means the final layer.')

flags.DEFINE_float(
    'temperature', 0.3,
    'Temperature parameter for contrastive loss.')

flags.DEFINE_boolean(
    'hidden_norm', True,
    'L2 Normalization Vector representation.')

flags.DEFINE_enum(
    'downsample_mod', 'space_to_depth', ['space_to_depth', 'maxpooling','averagepooling'],
    'How the head upsample is done.')

# -----------------------------------------
# Configure Model Training
# -----------------------------------------

# Self-Supervised training and Supervised training mode
flags.DEFINE_enum(
    'mode', 'train', ['train', 'eval', 'train_then_eval'],
    'Whether to perform training or evaluation.')

flags.DEFINE_enum(
    'train_mode', 'pretrain', ['pretrain', 'finetune'],
    'The train mode controls different objectives and trainable components.')

flags.DEFINE_bool('lineareval_while_pretraining', True,
                  'Whether to finetune supervised head while pretraining.')

flags.DEFINE_enum(
    'aggregate_loss', 'contrastive_supervised', [
        'contrastive', 'contrastive_supervised', ],
    'Consideration update Model with One Contrastive or sum up and (Contrastive + Supervised Loss).')

flags.DEFINE_enum(
    'non_contrast_binary_loss', 'sum_symetrize_l2_loss_object_backg', [
        'Original_loss_add_contrast_level_object', 'sum_symetrize_l2_loss_object_backg', 'original_add_backgroud'],
    'Consideration update Model with One Contrastive or sum up and (Contrastive + Supervised Loss).')

flags.DEFINE_float(
    # Alpha Weighted loss (Objec & Background) [binary_mask_nt_xent_object_backgroud_sum_loss]
    'alpha', 0.99,
    'Alpha value is configuration the weighted of Object and Background in Model Total Loss.'
)
flags.DEFINE_float(
    # Weighted loss is the scaling term between  [weighted_loss]*Binary & [1-weighted_loss]*original contrastive loss)
    'weighted_loss', 0.8,
    'weighted_loss value is configuration the weighted of original and Binary contrastive loss.'
)

# Fine Tuning configure

flags.DEFINE_bool(
    'zero_init_logits_layer', False,
    'If True, zero initialize layers after avg_pool for supervised learning.')

flags.DEFINE_integer(
    'fine_tune_after_block', -1,
    'The layers after which block that we will fine-tune. -1 means fine-tuning '
    'everything. 0 means fine-tuning after stem block. 4 means fine-tuning '
    'just the linear head.')

# -----------------------------------------
# Configure Saving and Restore Model
# -----------------------------------------

# Saving Model

flags.DEFINE_string(
    'model_dir', "./model_ckpt/resnet_byol/projec_2048/",
    'Model directory for training.')

flags.DEFINE_integer(
    'keep_hub_module_max', 1,
    'Maximum number of Hub modules to keep.')

flags.DEFINE_integer(
    'keep_checkpoint_max', 5,
    'Maximum number of checkpoints to keep.')


# Loading Model

# Restore model weights only, but not global step and optimizer states
flags.DEFINE_string(
    'checkpoint', None,
    'Loading from the given checkpoint for fine-tuning if a finetuning '
    'checkpoint does not already exist in model_dir.')

flags.DEFINE_integer(
    'checkpoint_epochs', 1,
    'Number of epochs between checkpoints/summaries.')

flags.DEFINE_integer(
    'checkpoint_steps', 10,
    'Number of steps between checkpoints/summaries. If provided, overrides '
    'checkpoint_epochs.')


def main(argv):
    if len(argv) > 1:
        raise app.UsageError('Too many command-line arguments.')

    # Preparing dataset
    # Imagenet path prepare localy
    strategy = tf.distribute.MirroredStrategy()
    train_global_batch = FLAGS.train_batch_size * strategy.num_replicas_in_sync
    val_global_batch = FLAGS.val_batch_size * strategy.num_replicas_in_sync

    train_dataset = imagenet_dataset_single_machine(img_size=FLAGS.image_size, train_batch=train_global_batch,  val_batch=val_global_batch,
                                                    strategy=strategy, train_path=FLAGS.train_path,
                                                    val_path=FLAGS.val_path,
                                                    mask_path=FLAGS.mask_path, bi_mask=True,
                                                    train_label=FLAGS.train_label, val_label=FLAGS.val_label,
                                                    subset_class_num=FLAGS.num_classes)

    train_ds = train_dataset.simclr_inception_style_crop_image_mask()

    val_ds = train_dataset.supervised_validation()

    num_train_examples, num_eval_examples = train_dataset.get_data_size()

    train_steps = FLAGS.eval_steps or int(
        num_train_examples * FLAGS.train_epochs // train_global_batch)*2
      
    eval_steps = FLAGS.eval_steps or int(
        math.ceil(num_eval_examples / val_global_batch))

    epoch_steps = int(round(num_train_examples / train_global_batch))

    checkpoint_steps = (FLAGS.checkpoint_steps or (
        FLAGS.checkpoint_epochs * epoch_steps))
    
    
    logging.info("# Subset_training class %d", FLAGS.num_classes)
    logging.info('# train examples: %d', num_train_examples)
    logging.info('# train_steps: %d', train_steps)
    logging.info('# eval examples: %d', num_eval_examples)
    logging.info('# eval steps: %d', eval_steps)

    # Configure the Encoder Architecture.
    with strategy.scope():
        online_model = all_model.Binary_online_model(FLAGS.num_classes)
        prediction_model = all_model.prediction_head_model()
        target_model = all_model.Binary_target_model(FLAGS.num_classes)

    # Configure Wandb Training
    # Weight&Bias Tracking Experiment
    configs = {

        "Model_Arch": "ResNet50",
        "Training mode": "Binary_Non_Contrative_SSL",
        "DataAugmentation_types": "SimCLR_Inception_Croping_image_mask",
        "Dataset": "ImageNet1k",
        "object_backgroud_feature_Dsamp_method": FLAGS.downsample_mod,

        "IMG_SIZE": FLAGS.image_size,
        "Epochs": FLAGS.train_epochs,
        "Batch_size": train_global_batch,
        "Learning_rate": FLAGS.base_lr,
        "Temperature": FLAGS.temperature,
        "Optimizer": FLAGS.optimizer,
        "SEED": FLAGS.SEED,
        "Subset_dataset": FLAGS.num_classes, 
      
        "Loss configure": FLAGS.aggregate_loss,
        "Loss type": FLAGS.non_contrast_binary_loss,

    }

    wandb.init(project="heuristic_attention_representation_learning_v1",
               sync_tensorboard=True, config=configs)

    # Training Configuration
    # *****************************************************************
    # Only Evaluate model
    # *****************************************************************

    if FLAGS.mode == "eval":
        # can choose different min_interval
        for ckpt in tf.train.checkpoints_iterator(FLAGS.model_dir, min_interval_secs=15):
            result = perform_evaluation(
                online_model, val_ds, eval_steps, ckpt, strategy)
            # global_step from ckpt
            if result['global_step'] >= train_steps:
                logging.info('Evaluation complete. Existing-->')

    # *****************************************************************
    # Pre-Training and Evaluate
    # *****************************************************************
    else:
        summary_writer = tf.summary.create_file_writer(FLAGS.model_dir)

        with strategy.scope():

            # Configure the learning rate
            base_lr = FLAGS.base_lr
            scale_lr = FLAGS.lr_rate_scaling
            warmup_epochs = FLAGS.warmup_epochs
            train_epochs = FLAGS.train_epochs
            
            lr_schedule = WarmUpAndCosineDecay(
                base_lr, train_global_batch, num_train_examples, scale_lr, warmup_epochs,
                train_epochs=train_epochs, train_steps=train_steps)

            # Current Implement the Mixpercision optimizer
            optimizer = all_model.build_optimizer(lr_schedule)

            # Build tracking metrics
            all_metrics = []
            # Linear classfiy metric
            weight_decay_metric = tf.keras.metrics.Mean('train/weight_decay')
            total_loss_metric = tf.keras.metrics.Mean('train/total_loss')
            all_metrics.extend([weight_decay_metric, total_loss_metric])

            if FLAGS.train_mode == 'pretrain':
                # for contrastive metrics
                contrast_loss_metric = tf.keras.metrics.Mean(
                    'train/non_contrast_loss')
                contrast_acc_metric = tf.keras.metrics.Mean(
                    "train/non_contrast_acc")
                contrast_entropy_metric = tf.keras.metrics.Mean(
                    'train/non_contrast_entropy')
                all_metrics.extend(
                    [contrast_loss_metric, contrast_acc_metric, contrast_entropy_metric])

            if FLAGS.train_mode == 'finetune' or FLAGS.lineareval_while_pretraining:
                logging.info(
                    "Apllying pre-training and Linear evaluation at the same time")
                # Fine-tune architecture metrics
                supervised_loss_metric = tf.keras.metrics.Mean(
                    'train/supervised_loss')
                supervised_acc_metric = tf.keras.metrics.Mean(
                    'train/supervised_acc')
                all_metrics.extend(
                    [supervised_loss_metric, supervised_acc_metric])

            # Check and restore Ckpt if it available
            # Restore checkpoint if available.
            checkpoint_manager = try_restore_from_checkpoint(
                online_model, optimizer.iterations, optimizer)

            # Scale loss  --> Aggregating all Gradients
            def distributed_loss(o1, o2, b1, b2, alpha):

                if FLAGS.non_contrast_binary_loss == 'original_add_backgroud':
                    ob1 = tf.concat([o1, b1], axis=0)
                    ob2 = tf.concat([o2, b2], axis=0)
                    # each GPU loss per_replica batch loss
                    per_example_loss, logits_ab, labels = byol_symetrize_loss(
                        ob1, ob2,  temperature=FLAGS.temperature)

                elif FLAGS.non_contrast_binary_loss == 'sum_symetrize_l2_loss_object_backg':

                    # each GPU loss per_replica batch loss
                    per_example_loss, logits_ab, labels = sum_symetrize_l2_loss_object_backg(
                        o1, o2, b1, b2,  alpha=alpha, temperature=FLAGS.temperature)

                # total sum loss //Global batch_size
                loss = tf.reduce_sum(per_example_loss) * \
                    (1./train_global_batch)
                return loss, logits_ab, labels

            def distributed_Orginal_add_Binary_non_contrast_loss(x1, x2, v1, v2, img_1, img_2,):
                #Optional [binary_mask_nt_xent_object_backgroud_sum_loss, binary_mask_nt_xent_object_backgroud_sum_loss_v1]
                per_example_loss, logits_o_ab, labels = symetrize_l2_loss_object_level_whole_image(
                    x1, x2, v1, v2, img_1, img_2,  weight_loss=FLAGS.weighted_loss, temperature=FLAGS.temperature)

                # total sum loss //Global batch_size
                loss = tf.reduce_sum(per_example_loss) * \
                    (1./train_global_batch)

                return loss, logits_o_ab, labels

            @tf.function
            def train_step(ds_one, ds_two, alpha):

                # Get the data from
                images_mask_one, lable_1, = ds_one  # lable_one
                images_mask_two, lable_2,  = ds_two  # lable_two

                with tf.GradientTape(persistent=True) as tape:

                    obj_1, backg_1,  proj_head_output_1, supervised_head_output_1 = online_model(
                        [images_mask_one[0], tf.expand_dims(images_mask_one[1], axis=-1)], training=True)
                    # Vector Representation from Online encoder go into Projection head again
                    obj_1 = prediction_model(obj_1, training=True)
                    backg_1 = prediction_model(backg_1, training=True)
                    proj_head_output_1 = prediction_model(
                        proj_head_output_1, training=True)

                    obj_2, backg_2, proj_head_output_2, supervised_head_output_2 = target_model(
                        [images_mask_two[0], tf.expand_dims(images_mask_two[1], axis=-1)], training=True)

                    # Compute Contrastive Train Loss -->
                    loss = None
                    if proj_head_output_1 is not None:

                        # Compute Contrastive Loss model
                        if FLAGS.non_contrast_binary_loss == 'Original_loss_add_contrast_level_object':
                            loss, logits_o_ab, labels = distributed_Orginal_add_Binary_non_contrast_loss(obj_1, obj_2,  backg_1, backg_2,
                                                                                                         proj_head_output_1, proj_head_output_2)

                        else:
                            # Compute Contrastive Loss model
                            loss, logits_o_ab, labels = distributed_loss(
                                obj_1, obj_2,  backg_1, backg_2, alpha)

                        if loss is None:
                            loss = loss
                        else:
                            loss += loss

                        # Update Self-Supervised Metrics
                        metrics.update_pretrain_metrics_train(contrast_loss_metric,
                                                              contrast_acc_metric,
                                                              contrast_entropy_metric,
                                                              loss, logits_o_ab,
                                                              labels)

                    # Compute the Supervised train Loss
                    '''Consider Sperate Supervised Loss'''
                    # supervised_loss=None
                    if supervised_head_output_1 is not None:

                        if FLAGS.train_mode == 'pretrain' and FLAGS.lineareval_while_pretraining:

                            outputs = tf.concat(
                                [supervised_head_output_1, supervised_head_output_2], 0)
                            supervise_lable = tf.concat(
                                [lable_1, lable_2], 0)

                            # Calculte the cross_entropy loss with Labels
                            sup_loss = obj_lib.add_supervised_loss(
                                labels=supervise_lable, logits=outputs)

                            scale_sup_loss = tf.nn.compute_average_loss(
                                sup_loss, global_batch_size=train_global_batch)
                            # scale_sup_loss = tf.reduce_sum(
                            #     sup_loss) * (1./train_global_batch)
                            # Update Supervised Metrics
                            metrics.update_finetune_metrics_train(supervised_loss_metric,
                                                                  supervised_acc_metric, scale_sup_loss,
                                                                  supervise_lable, outputs)

                        '''Attention'''
                        # Noted Consideration Aggregate (Supervised + Contrastive Loss) --> Update the Model Gradient
                        if FLAGS.aggregate_loss == "contrastive_supervised":
                            if loss is None:
                                loss = scale_sup_loss
                            else:
                                loss += scale_sup_loss

                        elif FLAGS.aggregate_loss == "contrastive":

                            supervise_loss = None
                            if supervise_loss is None:
                                supervise_loss = scale_sup_loss
                            else:
                                supervise_loss += scale_sup_loss
                        else:
                            raise ValueError(
                                " Loss aggregate is invalid please check FLAGS.aggregate_loss")

                    weight_decay_loss = all_model.add_weight_decay(
                        online_model, adjust_per_optimizer=True)

                    # weight_decay_loss_scale = tf.nn.scale_regularization_loss(
                    #     weight_decay_loss)
                    # Under experiment Scale loss after adding Regularization and scaled by Batch_size
                    # weight_decay_loss = tf.nn.scale_regularization_loss(
                    #     weight_decay_loss)
                    weight_decay_metric.update_state(weight_decay_loss)
                    loss += weight_decay_loss
                    total_loss_metric.update_state(loss)

                    logging.info('Trainable variables:')
                    for var in online_model.trainable_variables:
                        logging.info(var.name)

                # Update Encoder and Projection head weight
                grads = tape.gradient(loss, online_model.trainable_variables)
                optimizer.apply_gradients(
                    zip(grads, online_model.trainable_variables))

                # Update Prediction Head model
                grads = tape.gradient(
                    loss, prediction_model.trainable_variables)
                optimizer.apply_gradients(
                    zip(grads, prediction_model.trainable_variables))
                del tape
                return loss

            @tf.function
            def distributed_train_step(ds_one, ds_two, alpha):
                per_replica_losses = strategy.run(
                    train_step, args=(ds_one, ds_two, alpha))
                return strategy.reduce(tf.distribute.ReduceOp.SUM, per_replica_losses,
                                       axis=None)
            global_step = optimizer.iterations

            for epoch in range(FLAGS.train_epochs):

                total_loss = 0.0
                num_batches = 0
                if epoch +1 <= 15: 
                    alpha=0.5
                elif epoch + 1 <= 35: 
                    alpha= 0.7
                elif epoch + 1 <= 50: 
                    alpha = 0.9
                # elif epoch + 1 <=50 : 
                #     alpha=0.97


                for _, (ds_one, ds_two) in enumerate(train_ds):
                
                    total_loss += distributed_train_step(ds_one, ds_two, alpha)
                    num_batches += 1

                    # Update weight of Target Encoder Every Step
                    beta = 0.99
                    target_encoder_weights = target_model.get_weights()
                    online_encoder_weights = online_model.get_weights()

                    for i in range(len(online_encoder_weights)):
                        target_encoder_weights[i] = beta * target_encoder_weights[i] + (
                            1-beta) * online_encoder_weights[i]
                    target_model.set_weights(target_encoder_weights)

                    # if (global_step.numpy()+ 1) % checkpoint_steps==0:

                    with summary_writer.as_default():
                        cur_step = global_step.numpy()
                        checkpoint_manager.save(cur_step)
                        logging.info('Completed: %d / %d steps',
                                     cur_step, train_steps)
                        metrics.log_and_write_metrics_to_summary(
                            all_metrics, cur_step)
                        tf.summary.scalar('learning_rate', lr_schedule(tf.cast(global_step, dtype=tf.float32)),
                                          global_step)
                        summary_writer.flush()

                epoch_loss = total_loss/num_batches
                # Wandb Configure for Visualize the Model Training
                wandb.log({
                    "epochs": epoch+1,
                    "train_contrast_loss": contrast_loss_metric.result(),
                    "train_contrast_acc": contrast_acc_metric.result(),
                    "train_contrast_acc_entropy": contrast_entropy_metric.result(),
                    "train/weight_decay": weight_decay_metric.result(),
                    "train/total_loss": epoch_loss,
                    "train/supervised_loss":    supervised_loss_metric.result(),
                    "train/supervised_acc": supervised_acc_metric.result(), 
                    "train/alpha_value": alpha,
                })
                for metric in all_metrics:
                    metric.reset_states()
                # Saving Entire Model
                if epoch + 1 == 50:
                    save_ = './model_ckpt/resnet_byol/binary_encoder_resnet50_mlp_run_1' + \
                        str(epoch) + ".h5"
                    online_model.save_weights(save_)

            logging.info('Training Complete ...')

        if FLAGS.mode == 'train_then_eval':
            perform_evaluation(online_model, val_ds, eval_steps,
                               checkpoint_manager.latest_checkpoint, strategy)


    # Pre-Training and Finetune
if __name__ == '__main__':

    app.run(main)
