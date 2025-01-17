import os
import sys

sys.path.append(os.path.dirname(os.path.realpath(__file__)))
sys.path.append(os.getcwd())

import numpy as np
import tensorflow as tf
from trainer.model import Model
from trainer.train_ops import TrainOps
from trainer.train_config import TrainConfig
from trainer.dataset_loader import DatasetLoader
from random import randint

try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO
from tensorflow.python.lib.io import file_io
from trainer.architecture import Architecture as Arch

def create_training_ops():

    # get trainers
    model = Model()
    train_d, train_g, loss_d, loss_g, generated_images, Dx, Dg = model.trainers()

    # initialize variables
    global_step_var = tf.Variable(0, name='global_step')
    epoch_var = tf.Variable(0, name='epoch')
    batch_var = tf.Variable(0, name='batch')

    # prepare summaries
    loss_d_summary_op = tf.summary.scalar('Discriminator_Loss', loss_d)
    loss_g_summary_op = tf.summary.scalar('Generator_Loss', loss_g)
    images_summary_op = tf.summary.image('Generated_Image', generated_images, max_outputs=1)
    summary_op = tf.summary.merge_all()

def one_hot(labels):
    num_cat = Arch.num_cat
    one_hot_labels = np.eye(num_cat)[labels]
    one_hot_labels = np.reshape(one_hot_labels, [-1, 1, 1, num_cat])
    return one_hot_labels

def expand_labels(labels):
    one_hot_labels = one_hot(labels)
    M = one_hot_labels.shape[0]
    img_size = Arch.img_size    
    expanded_labels = one_hot_labels * np.ones([M, img_size, img_size, Arch.num_cat])
    return (one_hot_labels, expanded_labels)

def generate_z(M):
    return np.random.normal(0.0, 1.0, size=[M, 1, 1, Arch.z_size])

def random_codes(M):
    z = generate_z(M)
    labels = [randint(0, 9) for i in range(M)]
    y, y_expanded = expand_labels(labels)
    return y, y_expanded, z

def increment(variable, sess):
    sess.run(tf.assign_add(variable, 1))
    new_val = sess.run(variable)
    return new_val

def checkpoint_model(checkpoint_dir, session, step, saver):
    if not os.path.exists(checkpoint_dir):
        os.makedirs(checkpoint_dir)
    model_name = checkpoint_dir + '/model-' + str(step) + '.cptk'
    saver.save(session, model_name, global_step=step)
    print("saved checkpoint!")

def sample_category(sess, ops, config, category, num_samples, sub_dir):
    
    # prepare for calling generator
    labels = [category] * num_samples
    one_hot_labels = one_hot(labels)
    z = generate_z(num_samples)
    feed_dict = {
        'z_holder:0': z,
        'y_holder:0': one_hot_labels
    }

    # get images
    images = sess.run(ops.generated_images, feed_dict=feed_dict)
    images = images + 1.
    images = images * 128.

    # write to disk
    for i in range(images.shape[0]):
        image = images[i]
        img_tensor = tf.image.encode_png(image)
        folder = config.sample_dir + '/' + sub_dir + '/' + str(category)
        if not os.path.exists(folder):
            os.makedirs(folder)
        img_name = folder + '/' + 'sample_' + str(i) + '.png'
        output_data = sess.run(img_tensor)
        with file_io.FileIO(img_name, 'w+') as f:
            f.write(output_data)
            f.close

def sample_all_categories(sess, ops, config, num_samples, sub_dir):
    categories = [i for i in range(Arch.num_cat)]
    for category in categories:
        sample_category(sess, ops, config, category, num_samples, sub_dir)

def load_session(config):
    sess = tf.Session()

    # load stored graph into current graph
    graph_filename = str(tf.train.latest_checkpoint(config.checkpoint_dir)) + '.meta'
    saver = tf.train.import_meta_graph(graph_filename)

    # restore variables into graph
    saver.restore(sess, tf.train.latest_checkpoint(config.checkpoint_dir))
        
    # load operations 
    ops = TrainOps()
    ops.populate(sess)
    return sess, ops

def sample(config):
    sess, ops = load_session(config)
    num_samples = int(config.sample)
    sample_all_categories(sess, ops, config, num_samples, 'all_samples')

def train(sess, ops, config):
    writer = tf.summary.FileWriter(config.summary_dir, graph=tf.get_default_graph())
    saver = tf.train.Saver()

    # prepare data
    loader = DatasetLoader()
    dataset, num_batches = loader.load_dataset(config)
    iterator = dataset.make_initializable_iterator()
    next_batch = iterator.get_next()

    # counters
    epoch = sess.run(ops.epoch_var)
    batch = sess.run(ops.batch_var)
    global_step = sess.run(ops.global_step_var)

    # loop over epochs
    while epoch < config.num_epochs:

        # draw samples
        sample_all_categories(sess, ops, config, 5, 'epoch_' + str(epoch))

        sess.run(iterator.initializer)

        # loop over batches
        while batch < num_batches:

            images, labels = sess.run(next_batch)
            _, expanded_labels = expand_labels(labels)
            M = images.shape[0]
            y, y_expanded, z = random_codes(M)

            # run session
            feed_dict = {
                'images_holder:0': images, 
                'labels_holder:0': expanded_labels,
                'y_expanded_holder:0': y_expanded,
                'z_holder:0': z,
                'y_holder:0': y
            }
            sess.run(ops.train_d, feed_dict=feed_dict)
            sess.run(ops.train_g, feed_dict=feed_dict)

            # logging
            if global_step % config.log_freq == 0:
                summary = sess.run(ops.summary_op, feed_dict=feed_dict)
                writer.add_summary(summary, global_step=global_step)

                loss_d_val = sess.run(ops.loss_d, feed_dict=feed_dict)
                loss_g_val = sess.run(ops.loss_g, feed_dict=feed_dict)
                print("epoch: " + str(epoch) + ", batch " + str(batch))
                print("G loss: " + str(loss_g_val))
                print("D loss: " + str(loss_d_val))

            # saving

            if global_step % config.checkpoint_freq == 0:
                checkpoint_model(config.checkpoint_dir, sess, global_step, saver)

            global_step = increment(ops.global_step_var, sess)
            batch = increment(ops.batch_var, sess)

        epoch = increment(ops.epoch_var, sess)
        sess.run(tf.assign(ops.batch_var, 0))
        batch = sess.run(ops.batch_var)

    sess.close()


def begin_training(config):
    create_training_ops()
    sess = tf.Session()
    sess.run(tf.global_variables_initializer())
    ops = TrainOps()
    ops.populate(sess)
    train(sess, ops, config)

def continue_training(config):
    sess, ops = load_session(config)
    train(sess, ops, config)

# Run
if __name__ == '__main__':
    config = TrainConfig()
    if config.sample > 0:
        sample(config)
    else:
        train_task = continue_training if config.should_continue else begin_training
        if config.cluster:

            import dask
            import dask.multiprocessing
            from dask.distributed import Client
            from dask_drmaa import SGECluster

            memory = 2 ** 36

            job = dask.delayed(train_task)(config)

            # start cluster workers
            cluster = SGECluster()
            client = Client(cluster)
            cluster.start_workers(1, memory=memory)
            print("Web interface opened on port {}".format(client.scheduler_info()["services"]["bokeh"]))

            # start the actual computation
            results = dask.compute(job, get=client.get)
            print(results)

            # shut down all workers
            cluster.close()
        else:
            res = train_task(config)
            print(res)
