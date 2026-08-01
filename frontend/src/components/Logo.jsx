import React from 'react';

export default function Logo({ width = 180, height = 36 }) {
  return (
    <svg 
      width={width} 
      height={height} 
      viewBox="0 0 180 36" 
      fill="none" 
      xmlns="http://www.w3.org/2000/svg"
      style={{ display: 'inline-block', verticalAlign: 'middle' }}
    >
      {/* Icon Group */}
      <g id="LogoIcon">
        {/* Slanted F Polygon Frame */}
        <path 
          d="M2 2H28L22 14H14V20H22L19 26H14V34H8V2Z" 
          fill="#ffffff" 
        />
        
        {/* Inner Fibonacci Spiral Detail (Dark lines inside F) */}
        <path 
          d="M14 6A8 8 0 0 1 22 14M14 10A4 4 0 0 1 18 14" 
          stroke="#0d111a" 
          strokeWidth="1.5" 
          strokeLinecap="round" 
        />
        
        {/* Glowing Candlestick Bars (Slanted along the right wing) */}
        <rect x="29" y="4" width="2.5" height="12" rx="1" fill="#00e676" transform="skewX(-15)" />
        <rect x="33" y="2" width="2.5" height="16" rx="1" fill="#00e676" transform="skewX(-15)" />
        <rect x="37" y="7" width="2.5" height="9" rx="1" fill="#00e676" transform="skewX(-15)" />
      </g>
      
      {/* Brand Name Text */}
      <text 
        x="48" 
        y="25" 
        fontFamily="'Outfit', 'Inter', sans-serif" 
        fontSize="17" 
        fontWeight="800" 
        fill="#ffffff" 
        letterSpacing="0.5px"
      >
        FIB <tspan fontWeight="400" fill="#e2e8f0">Trader</tspan> <tspan fontWeight="800" fill="#00e676">AI</tspan>
      </text>
    </svg>
  );
}
