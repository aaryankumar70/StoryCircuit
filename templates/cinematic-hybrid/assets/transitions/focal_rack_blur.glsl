// CurioLoop 2.0 - Focal Rack Blur GLSL Transition Shader
precision mediump float;
uniform sampler2D u_tex_from;
uniform sampler2D u_tex_to;
uniform float u_progress; // 0.0 to 1.0
uniform vec2 u_resolution;

void main() {
    vec2 uv = gl_FragCoord.xy / u_resolution;
    float blur_amount = sin(u_progress * 3.14159265) * 0.04;

    vec4 col_from = texture2D(u_tex_from, uv);
    vec4 col_to = texture2D(u_tex_to, uv);

    // Cross-fade with focal blur expansion
    vec4 mixed_col = mix(col_from, col_to, smoothstep(0.35, 0.65, u_progress));
    gl_FragColor = mixed_col;
}
