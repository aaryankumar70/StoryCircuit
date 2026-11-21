// CurioLoop 2.0 - PBR-Lite Material Shader Library
precision mediump float;
uniform vec3 u_light_dir;
uniform vec3 u_view_dir;

// Aged Parchment Material Function
vec3 evaluateParchment(vec3 baseColor, vec3 normal, float roughness) {
    float NdotL = max(dot(normal, u_light_dir), 0.0);
    vec3 diffuse = baseColor * (NdotL * 0.8 + 0.2);
    return diffuse;
}

// Brushed Brass / Gyro Gimbal Material
vec3 evaluateBrushedBrass(vec3 baseColor, vec3 normal, float roughness) {
    float NdotL = max(dot(normal, u_light_dir), 0.0);
    vec3 halfVec = normalize(u_light_dir + u_view_dir);
    float NdotH = max(dot(normal, halfVec), 0.0);
    float spec = pow(NdotH, 32.0 / roughness);
    return baseColor * NdotL + vec3(1.0, 0.9, 0.6) * spec * 0.7;
}
