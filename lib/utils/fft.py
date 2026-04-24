"""
Custom FFT implementation for MicroPython
Implements Cooley-Tukey radix-2 FFT algorithm without external dependencies.

This module provides FFT functionality for microwave sensor signal processing
when ulab is not available. It uses only built-in Python and cmath modules.
"""

import cmath
import math


def _next_power_of_2(n):
    """
    Find the next power of 2 greater than or equal to n.
    
    Args:
        n: Input number
    
    Returns:
        Next power of 2 >= n
    """
    if n <= 0:
        return 1
    # Check if already power of 2
    if n & (n - 1) == 0:
        return n
    # Find next power of 2
    power = 1
    while power < n:
        power <<= 1
    return power


def _bit_reverse_copy(data, n):
    """
    Reorder array elements using bit-reversal permutation.
    This is required for the iterative FFT algorithm.
    
    Args:
        data: Input list of complex numbers
        n: Length (must be power of 2)
    
    Returns:
        Bit-reversed copy of data
    """
    result = [0] * n
    bits = int(math.log2(n))
    
    for i in range(n):
        # Reverse bits of i
        rev = 0
        for j in range(bits):
            if i & (1 << j):
                rev |= 1 << (bits - 1 - j)
        result[rev] = data[i]
    
    return result


def fft(data, yield_interval=None):
    """
    Compute FFT using iterative Cooley-Tukey radix-2 algorithm.
    
    This is a memory-efficient implementation that works without numpy/ulab.
    The algorithm:
    1. Pads input to next power of 2 if needed
    2. Performs bit-reversal permutation
    3. Iteratively computes FFT using butterfly operations
    
    Time complexity: O(N log N) where N is the padded length
    Space complexity: O(N)
    
    Args:
        data: List of complex numbers or real numbers (will be converted to complex)
        yield_interval: If provided, yields control every N butterfly operations (for async)
    
    Returns:
        List of complex numbers representing frequency domain
    
    Example:
        >>> signal = [1.0, 2.0, 3.0, 4.0]
        >>> spectrum = fft(signal)
        >>> magnitudes = [abs(x) for x in spectrum]
    """
    if not data:
        return []
    
    n = len(data)
    
    # Convert to complex if needed and pad to power of 2
    n_padded = _next_power_of_2(n)
    
    # Convert input to complex numbers and pad with zeros
    complex_data = []
    for i in range(n_padded):
        if i < n:
            val = data[i]
            if isinstance(val, complex):
                complex_data.append(val)
            else:
                complex_data.append(complex(val, 0))
        else:
            complex_data.append(complex(0, 0))
    
    # Bit-reversal permutation
    a = _bit_reverse_copy(complex_data, n_padded)
    
    # Iterative FFT using Cooley-Tukey algorithm
    # Process in stages, each stage doubles the DFT size
    m = 2
    butterfly_count = 0  # Track operations for cooperative yielding
    
    while m <= n_padded:
        # Compute twiddle factor for this stage
        # w_m = e^(-2πi/m) is the principal m-th root of unity
        theta = -2.0 * math.pi / m
        w_m = complex(math.cos(theta), math.sin(theta))
        
        # Process each DFT of size m
        for k in range(0, n_padded, m):
            w = complex(1, 0)  # Start with w^0 = 1
            
            # Butterfly operations for this DFT
            for j in range(m // 2):
                # Indices for butterfly
                t_idx = k + j + m // 2
                u_idx = k + j
                
                # Butterfly computation
                # t = w * a[t_idx]
                t = complex(
                    w.real * a[t_idx].real - w.imag * a[t_idx].imag,
                    w.real * a[t_idx].imag + w.imag * a[t_idx].real
                )
                u = a[u_idx]
                
                # Update values
                a[u_idx] = complex(u.real + t.real, u.imag + t.imag)
                a[t_idx] = complex(u.real - t.real, u.imag - t.imag)
                
                # Update twiddle factor: w = w * w_m
                w = complex(
                    w.real * w_m.real - w.imag * w_m.imag,
                    w.real * w_m.imag + w.imag * w_m.real
                )
                
                # Cooperative yielding: periodically yield control
                # This is a no-op in sync context but allows async wrapper
                butterfly_count += 1
                if yield_interval and butterfly_count >= yield_interval:
                    butterfly_count = 0
                    # Note: actual yielding must be done by async wrapper
                    # This just provides a hook point
        
        m *= 2
    
    return a


def mean(data):
    """
    Calculate arithmetic mean of a list.
    
    Args:
        data: List of numbers
    
    Returns:
        Mean value as float
    """
    if not data:
        return 0.0
    return sum(data) / len(data)


def abs_spectrum(fft_result):
    """
    Calculate magnitude spectrum from FFT result.
    
    Args:
        fft_result: List of complex numbers from fft()
    
    Returns:
        List of magnitudes (absolute values)
    """
    return [abs(x) for x in fft_result]


def argmax(data, start=0, end=None):
    """
    Find index of maximum value in a list or slice.
    
    Args:
        data: List of numbers
        start: Start index (inclusive)
        end: End index (exclusive), None means end of list
    
    Returns:
        Index of maximum value
    """
    if not data:
        return 0
    
    if end is None:
        end = len(data)
    
    max_idx = start
    max_val = data[start]
    
    for i in range(start + 1, end):
        if data[i] > max_val:
            max_val = data[i]
            max_idx = i
    
    return max_idx


# Compatibility layer to mimic numpy-like interface
class FFTModule:
    """
    Provides numpy.fft-like interface for compatibility.
    """
    @staticmethod
    def fft(data):
        """
        Compute FFT with numpy-like interface.
        Accepts complex arrays (real + 1j * imag).
        
        Args:
            data: List or array-like of numbers or complex numbers
        
        Returns:
            List of complex FFT results
        """
        return fft(data)


# Create module-level fft object for numpy-like usage
fft_module = FFTModule()


# Example usage and test
if __name__ == "__main__":
    print("Testing custom FFT implementation...")
    
    # Test 1: Simple signal
    print("\nTest 1: DC signal")
    signal = [1.0, 1.0, 1.0, 1.0]
    result = fft(signal)
    mags = abs_spectrum(result)
    print(f"Input: {signal}")
    print(f"FFT magnitudes: {[round(m, 2) for m in mags]}")
    print(f"Peak at bin: {argmax(mags)}")
    
    # Test 2: Sine wave
    print("\nTest 2: Sine wave (1 Hz in 8 samples)")
    signal = [math.sin(2 * math.pi * i / 8) for i in range(8)]
    result = fft(signal)
    mags = abs_spectrum(result)
    print(f"Input: {[round(s, 2) for s in signal]}")
    print(f"FFT magnitudes: {[round(m, 2) for m in mags]}")
    print(f"Peak at bin: {argmax(mags[1:]) + 1} (excluding DC)")
    
    # Test 3: Complex input (I/Q)
    print("\nTest 3: Complex I/Q signal")
    i_samples = [1.0, 0.0, -1.0, 0.0]
    q_samples = [0.0, 1.0, 0.0, -1.0]
    complex_signal = [complex(i, q) for i, q in zip(i_samples, q_samples)]
    result = fft(complex_signal)
    mags = abs_spectrum(result)
    print(f"I samples: {i_samples}")
    print(f"Q samples: {q_samples}")
    print(f"FFT magnitudes: {[round(m, 2) for m in mags]}")
    
    # Test 4: Mean function
    print("\nTest 4: Mean calculation")
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    print(f"Data: {data}")
    print(f"Mean: {mean(data)}")
    
    print("\nAll tests completed!")

# Made with Bob
