import sys
import time
import numpy as np
from keras.activations import relu
from scipy.io.wavfile import read, write
from keras.models import Model, Sequential
from keras.layers import Convolution1D, AtrousConvolution1D, Flatten, Dense, \
    Input, Lambda, merge


def wavenetBlock(n_atrous_filters, atrous_filter_size, atrous_rate,
                 n_conv_filters, conv_filter_size):
    def f(input):
        l1 = AtrousConvolution1D(n_atrous_filters, atrous_filter_size,
                                 atrous_rate=atrous_rate,
                                 border_mode='same')(input)
        l2a = Convolution1D(n_conv_filters, conv_filter_size,
                            activation='tanh', border_mode='same')(l1)
        l2b = Convolution1D(n_conv_filters, conv_filter_size,
                            activation='sigmoid', border_mode='same')(l1)
        l2 = merge([l2a, l2b], mode='mul')
        l3 = Convolution1D(1, 1, activation='relu', border_mode='same')(l2)
        l4 = merge([l3, input], mode='sum')
        return l4, l3
    return f


def get_basic_generative_model(input_size):
    input = Input(shape=(input_size, 1))
    l1a, l1b = wavenetBlock(64, 2, 2, 64, 3)(input)
    l2a, l2b = wavenetBlock(128, 2, 4, 64, 3)(l1a)
    l3a, l3b = wavenetBlock(256, 2, 8, 64, 3)(l2a)
    l4a, l4b = wavenetBlock(1024, 2, 16, 64, 3)(l3a)
    l5 = merge([l1b, l2b, l3b, l4b], mode='sum')
    l6 = Lambda(relu)(l5)
    l7 = Convolution1D(1, 1, activation='relu')(l6)
    l8 = Convolution1D(1, 1)(l7)
    l9 = Flatten()(l8)
    l10 = Dense(256, activation='softmax')(l9)
    model = Model(input=input, output=l10)
    model.compile(loss='categorical_crossentropy', optimizer='rmsprop',
                  metrics=['accuracy'])
    model.summary()
    return model


def get_audio(filename):
    sr, audio = read(filename)
    audio = audio.astype(float)
    audio = audio - audio.min()
    audio = audio / (audio.max() - audio.min())
    audio = (audio - 0.5) * 2
    return sr, audio


def frame_generator(sr, audio, frame_size, frame_shift):
    audio_len = len(audio)
    while 1:
        for i in range(0, audio_len - frame_size - 1, frame_shift):
            frame = audio[i:i+frame_size]
            if len(frame) < frame_size:
                break
            if i + frame_size + 1 >= audio_len:
                break
            temp = audio[i + frame_size + 1]
            target_val = int((np.sign(temp) * (np.log(1 + 256*abs(temp)) / (
                np.log(1+256))) + 1)/2.0 * 255)
            yield frame.reshape(1, frame_size, 1), \
                (np.eye(256)[target_val]).reshape(1, 256)


if __name__ == '__main__':
    n_epochs = 1000
    frame_size = 2048
    frame_shift = 128
    sr_training, training_audio = get_audio('train.wav')
    # training_audio = training_audio[:sr_training*1200]
    sr_valid, valid_audio = get_audio('validate.wav')
    # valid_audio = valid_audio[:sr_valid*60]
    assert sr_training == sr_valid, "Training, validation samplerate mismatch"
    n_training_examples = int((len(training_audio)-frame_size-1) / float(
        frame_shift))
    n_validation_examples = int((len(valid_audio)-frame_size-1) / float(
        frame_shift))
    model = get_basic_generative_model(frame_size)
    print 'Total training examples:', n_training_examples
    print 'Total validation examples:', n_validation_examples
    model.fit_generator(frame_generator(sr_training, training_audio,
                                        frame_size, frame_shift),
                        samples_per_epoch=1000,
                        nb_epoch=n_epochs,
                        validation_data=frame_generator(sr_valid, valid_audio,
                                                        frame_size, frame_shift
                                                        ),
                        nb_val_samples=100,
                        verbose=1)
    print 'Saving model...'
    str_timestamp = str(int(time.time()))
    model.save('models/model_'+str_timestamp+'_'+str(n_epochs)+'.h5')
    print 'Generating audio...'
    new_audio = np.zeros((sr_training * 1))
    curr_sample_idx = 0
    audio_context = valid_audio[:frame_size]
    while curr_sample_idx < new_audio.shape[0]:
        distribution = np.array(model.predict(audio_context.
                                reshape(1, frame_size, 1)), dtype=float
                                ).reshape(256)
        distribution /= distribution.sum().astype(float)
        predicted_val = np.random.choice(range(256), p=distribution)
        ampl_val_8 = ((((predicted_val) / 255.0) - 0.5) * 2.0)
        ampl_val_16 = (np.sign(ampl_val_8) * (1/256.0) * ((1 + 256.0)**abs(
            ampl_val_8) - 1)) * 2**15
        new_audio[curr_sample_idx] = ampl_val_16
        audio_context[-1] = ampl_val_16
        audio_context[:-1] = audio_context[1:]
        pc_str = str(round(100*curr_sample_idx/float(new_audio.shape[0]), 2))
        sys.stdout.write('Percent complete: ' + pc_str + '\r')
        sys.stdout.flush()
        curr_sample_idx += 1
    outfilepath = 'output/generated_'+str_timestamp+'.wav'
    print 'Writing generated audio to:', outfilepath
    write(outfilepath, sr_training, new_audio.astype(np.int16))
    print '\nDone!'
