#version 330 core

uniform float u_brightness;

in vec3 v_color;
out vec4 fragColor;

void main() {
    vec2  d    = gl_PointCoord - vec2(0.5);
    float dist = length(d);
    if (dist > 0.5) discard;
    float alpha = smoothstep(0.5, 0.0, dist) * u_brightness;
    fragColor   = vec4(v_color, alpha);
}
