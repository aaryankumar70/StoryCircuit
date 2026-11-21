// CurioLoop 2.0 - Volumetric Fog GLSL Fragment Shader
// Raymarching procedural 3D fractional Brownian motion fog
precision mediump float;

uniform vec2 u_resolution;
uniform float u_time;
uniform vec3 u_light_direction;
uniform vec3 u_fog_color;
uniform float u_fog_density;

float hash(vec3 p) {
    p = fract(p * 0.3183099 + 0.1);
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float noise(in vec3 x) {
    vec3 i = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash(i + vec3(0,0,0)), hash(i + vec3(1,0,0)), f.x),
                   mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
               mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x),
                   mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
}

float fbm(vec3 p) {
    float f = 0.0;
    f += 0.5000 * noise(p); p = p * 2.02;
    f += 0.2500 * noise(p); p = p * 2.03;
    f += 0.1250 * noise(p); p = p * 2.01;
    f += 0.0625 * noise(p);
    return f;
}

void main() {
    vec2 uv = (gl_FragCoord.xy - 0.5 * u_resolution) / u_resolution.y;
    vec3 ray_origin = vec3(0.0, 0.0, -2.0);
    vec3 ray_dir = normalize(vec3(uv, 1.0));

    float density_acc = 0.0;
    float t = 0.2;
    for(int i = 0; i < 24; i++) {
        vec3 p = ray_origin + ray_dir * t;
        p.z += u_time * 0.08;
        float d = fbm(p * 1.5) * u_fog_density;
        density_acc += d * (1.0 - density_acc);
        t += 0.12;
        if(density_acc >= 0.95) break;
    }

    vec3 light_dir = normalize(u_light_direction);
    float sun_scatter = max(dot(ray_dir, light_dir), 0.0);
    vec3 final_color = mix(u_fog_color, vec3(1.0, 0.9, 0.75), pow(sun_scatter, 4.0) * 0.5);

    gl_FragColor = vec4(final_color, density_acc * 0.85);
}
