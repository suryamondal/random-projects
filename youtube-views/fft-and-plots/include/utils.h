
#ifndef UTILS
#define UTILS

#include <iostream>
#include <cmath>
#include <vector>
#include <complex>

namespace utils {

  /** finds least n for search^n > val */
  int findExponent(const int val, const int search) {
    int pFactor = 0;
    while(1) {
      if(val >= std::pow(search,pFactor)) {
	pFactor++;
      } else {break;}
    }
    return pFactor;
  }
  
  /** interpolate (x,y) array into a new (x1,y1) array
   *
   * use it only for double or float.
   */
  template<typename T>
  int padData(const std::vector<T> &x,
	      const std::vector<T> &y,
	      std::vector<T> &x1,
	      std::vector<T> &y1,
	      const int newLength) {

    if(x.size()!=y.size()) {return 1;}
    if(int(x.size())>=newLength) {return 2;}
    
    x1.clear(); x1.reserve(newLength);
    y1.clear(); y1.reserve(newLength);

    T interVal = (x.back()-x.front())/(newLength-1);
    
    T startPos, endPos, startAmp, endAmp;
    int ampCnt = 0;
    for(int ij=0;ij<newLength;) {
      startPos = x[ampCnt];
      endPos   = x[ampCnt+1];
      startAmp = y[ampCnt];
      endAmp   = y[ampCnt+1];
      
      T newPos = x.front() + ij*interVal;
      
      if(newPos > endPos) {
	ampCnt++;
      } else {
	x1.push_back(newPos);
	y1.push_back(startAmp +
		     (newPos - startPos)*(endAmp - startAmp) /
		     (endPos - startPos));
	ij++;
      }
    } // for(int ij=0;ij<newLength;) {

    return 0;
  }
  
}


#endif
