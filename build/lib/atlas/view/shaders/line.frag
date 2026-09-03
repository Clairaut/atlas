#version 330 core

uniform float u_line_alpha;

in vec4 v_color;
out vec4 out_color;

void main() {
    out_color = vec4(v_color.rgb, v_color.a * u_line_alpha);
}
