#version 330 core

in vec2 in_pos;
in vec4 in_color;

uniform mat4 proj;

out vec4 v_color;

void main() {
    gl_Position = proj * vec4(in_pos, 0.0, 1.0);
    v_color = in_color;
}
