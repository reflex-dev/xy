import numpy as np

import xy.pyplot as plt

fs = 512.0
t = np.arange(2048) / fs
x = np.sin(2 * np.pi * 32 * t) + 0.2 * np.sin(2 * np.pi * 96 * t)
y = np.sin(2 * np.pi * 32 * t + 0.3)

fig, axes = plt.subplots(2, 3, figsize=(11, 6))
axes[0, 0].psd(x, NFFT=256, Fs=fs, noverlap=128)
axes[0, 1].magnitude_spectrum(x, Fs=fs, pad_to=256)
axes[0, 2].phase_spectrum(x, Fs=fs, pad_to=256)
axes[1, 0].cohere(x, y, NFFT=256, Fs=fs, noverlap=128)
axes[1, 1].specgram(x, NFFT=256, Fs=fs, noverlap=128)
axes[1, 2].xcorr(x, y, maxlags=20)
