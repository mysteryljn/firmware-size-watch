/* Synthetic freestanding fixture: no hardware access or runtime startup. */
volatile unsigned initialized = 7;
volatile unsigned uninitialized[16];
const char message[] = "firmware size fixture";
void _start(void) {
    uninitialized[0] = initialized + (unsigned) message[0];
    for (;;) { }
}
