
#include "fft.h"

void fft::dft::DFT(CNArray& x) {
  
  const int N = x.size();
  if (N <= 1) return;

  // divide
  CNArray even, odd;
  even.clear(); odd.clear();
  for (int k = 0; k < N; k += 2) {
    if(k+1 == N) {break;}
    even.push_back(x[k]);
    odd.push_back(x[k+1]);
  }
  
  // compute
  fft::dft::DFT(even);
  fft::dft::DFT(odd);

  // combine
  for (int k = 0; k < N/2; k++) {
    Complex t = std::polar(1.0, - 2. * TMath::Pi() * k / N) * odd[k];
    x[k    ] = even[k] + t;
    x[k+N/2] = even[k] - t;
  }  
}

void fft::dft::iDFT(CNArray& x) {

  const int N = x.size();

  // conjugate the complex numbers
  for (int k=0;k<N;k++) {
    x[k] = std::conj(x[k]);
  }

  // forward fft
  fft::dft::DFT(x);

  // conjugate the complex numbers again
  for (int k=0;k<N;k++) {
    x[k] = std::conj(x[k]);
  }

  // scaling
  for (int k=0;k<N;k++) {
    x[k] /= N;
  }
}

void fft::dft::copyHalfArray() {
  halfOutputArray.reserve(arraySize/2);
  halfOutputArray.assign(outputArray.begin(),
			 (outputArray.begin() +
			  arraySize/2 - 1));
}

