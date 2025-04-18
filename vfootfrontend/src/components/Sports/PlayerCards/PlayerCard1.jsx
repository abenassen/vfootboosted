const statistics = [
    {
        label: 'Wins',
        value: 17,
    },
    {
        label: 'Losses',
        value: 9,
    },
    {
        label: 'Points',
        value: 461,
    },
];

export default function PlayerCard1() {
    return (
        <div className="mx-auto w-[380px] px-5">
            <div className="rounded-3xl border border-custom-gray-200 bg-custom-gray-100 dark:border-custom-gray-600 dark:bg-custom-gray-700">
                <div className="rounded-3xl bg-white p-4 ring-1 ring-custom-gray-200 dark:bg-custom-gray-800 dark:ring-custom-gray-600">
                    <div className="relative overflow-hidden pb-3">
                        <div className="overflow-hidden [filter:url('#rounded')]">
                            <div className="relative h-[400px] border border-custom-gray-200 bg-gradient-to-b from-custom-orange to-custom-yellow [clip-path:polygon(0_0,_100%_0,_100%_95%,_50%_100%,_0_95%)] dark:border-custom-gray-600">
                                <div className="pointer-events-none absolute start-1/2 top-10 -z-10 ms-8 -translate-x-1/2 text-center text-9xl/[0.8em] font-extrabold uppercase italic tracking-tighter text-white opacity-40 mix-blend-overlay">
                                    <div>James</div>
                                    <div>Sporty</div>
                                </div>
                                <img
                                    src="https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-1.png"
                                    alt="Player"
                                    className="absolute start-1/2 top-2 max-w-[calc(100%+60px)] -translate-x-1/2"
                                />
                            </div>
                        </div>

                        <div className="absolute bottom-0 start-1/2 flex h-12 w-12 -translate-x-1/2 items-center justify-center rounded-2xl bg-gradient-to-b from-custom-orange to-custom-yellow text-2xl/none font-extrabold tracking-tighter text-white">
                            26
                        </div>

                        <div className="absolute start-0 top-0 aspect-square w-[76px] -translate-x-1/2 -translate-y-1/2 rounded-full border border-custom-gray-200 bg-white dark:border-custom-gray-600 dark:bg-custom-gray-800">
                            <svg
                                viewBox="0 0 420 420"
                                fill="none"
                                xmlns="http://www.w3.org/2000/svg"
                                className="absolute bottom-4 end-4 h-5 w-5 text-team-golden-primary"
                            >
                                <path
                                    d="M201.646 416.137C144.946 389.951 97.469 343.545 60.543 278.221C30.33 224.771 13.58 169.737 4.849 132.979L0 112.558L20.478 108.517C29.676 106.701 36.353 98.519 36.353 89.064C36.353 87.535 36.171 85.986 35.811 84.46L31.579 64.862L68.813 56.045V18.129L83.947 14.518C125.355 4.884 167.706 0 210.202 0C252.699 0 294.762 4.884 336.17 14.518L351.208 18.129V56.045L388.444 64.862L384.015 84.461C383.657 85.986 383.572 87.538 383.572 89.064C383.572 98.519 390.297 106.701 399.497 108.517L420 112.558L415.161 132.981C406.428 169.739 389.684 224.774 359.473 278.221C322.549 343.545 275.075 389.95 218.367 416.141L210.01 420L201.646 416.137Z"
                                    fill="currentColor"
                                />
                                <path
                                    d="M210 26C249.08 26 288.199 30.49 326.273 39.344L330.666 40.365V44.899V76.042L357.217 82.392L362.729 83.71L361.421 89.253C360.846 91.694 360.555 94.187 360.555 96.66C360.555 111.915 371.342 125.116 386.206 128.049L392 129.194L390.628 134.969C382.592 168.782 367.193 219.379 339.47 268.405C306.042 327.514 263.28 369.405 212.366 392.909L210.001 394L207.635 392.908C156.723 369.404 113.959 327.513 80.531 268.404C52.807 219.379 37.408 168.782 29.373 134.968L28 129.193L33.795 128.048C48.658 125.115 59.446 111.914 59.446 96.659C59.446 94.185 59.154 91.692 58.579 89.252L57.272 83.709L62.784 82.391L89.335 76.041V44.898V40.365L93.727 39.344C131.802 30.49 170.921 26 210 26Z"
                                    className="fill-custom-gray-900"
                                />
                                <path
                                    d="M210 34C247.854 34 285.747 38.279 322.666 46.722V76.042V82.355L328.806 83.823L353.174 89.651C352.763 91.972 352.555 94.321 352.555 96.661C352.555 114.914 364.931 130.818 382.308 135.36C374.25 168.639 359.165 217.325 332.506 264.466C300.136 321.705 258.926 362.315 210.001 385.186C161.075 362.314 119.865 321.706 87.496 264.466C60.837 217.324 45.752 168.638 37.695 135.359C55.073 130.817 67.447 114.914 67.447 96.66C67.447 94.322 67.239 91.973 66.827 89.65L91.196 83.822L97.335 82.354V76.041V46.721C134.252 38.28 172.149 34 210 34ZM210 26C170.921 26 131.801 30.49 93.728 39.344L89.336 40.365V44.898V76.042L62.785 82.392L57.273 83.71L58.58 89.253C59.155 91.693 59.447 94.187 59.447 96.66C59.447 111.915 48.659 125.116 33.796 128.049L28 129.193L29.374 134.968C37.409 168.781 52.808 219.378 80.532 268.404C113.96 327.513 156.723 369.404 207.636 392.908L210.002 394L212.367 392.908C263.28 369.404 306.043 327.513 339.471 268.404C367.195 219.379 382.593 168.782 390.629 134.968L392.001 129.193L386.207 128.048C371.343 125.115 360.556 111.914 360.556 96.659C360.556 94.185 360.847 91.693 361.422 89.252L362.73 83.709L357.218 82.391L330.667 76.041V44.899V40.365L326.274 39.344C288.199 30.49 249.08 26 210 26Z"
                                    className="fill-white"
                                />
                                <path
                                    fillRule="evenodd"
                                    clipRule="evenodd"
                                    d="M210.044 114C210.044 114 254.447 142.648 304.491 145.051C304.491 145.051 309.988 171.923 307.221 198.278C307.221 198.278 290.07 198.51 271.19 193.843C271.19 193.843 272.964 183.446 272.282 177.209C272.282 177.209 233.793 170.418 210.044 156.694C210.044 156.694 176.743 171.387 148.354 177.209C148.354 177.209 147.671 197.724 152.175 213.249C152.175 213.249 187.661 208.121 210.044 197.17C210.044 197.17 251.399 215.883 305.038 217.131C305.038 217.131 282.199 303.81 210.044 338.001C210.044 338.001 163.094 319.519 135.797 272.021C135.797 272.021 156.36 271.283 175.732 266.654C176.721 268.349 192.58 281.955 210.044 293.092C210.044 293.092 238.889 281.727 255.903 247.625C255.903 247.625 227.878 244.113 210.044 236.537C210.044 236.537 169.281 250.767 127.061 252.617C127.061 252.617 103.859 207.151 115.051 144.498C115.051 144.498 168.007 144.497 210.044 114Z"
                                    fill="currentColor"
                                />
                                <path
                                    d="M218.323 65.462L210.24 49L202.157 65.462L184.081 68.102L197.16 80.916L194.073 99.009L210.24 90.467L226.406 99.009L223.319 80.916L236.398 68.102L218.323 65.462ZM148.835 90.709L142.5 77.807L136.165 90.709L122 92.777L132.25 102.819L129.831 117L142.5 110.305L155.17 117L152.75 102.82L163 92.777L148.835 90.709ZM298 92.777L283.835 90.709L277.5 77.807L271.165 90.709L256.999 92.777L267.25 102.819L264.83 117L277.5 110.305L290.17 117L287.75 102.82L298 92.777Z"
                                    className="fill-white"
                                />
                            </svg>
                        </div>

                        <div className="absolute end-0 top-0 aspect-square w-[76px] -translate-y-1/2 translate-x-1/2 rounded-full border border-custom-gray-200 bg-white dark:border-custom-gray-600 dark:bg-custom-gray-800">
                            <svg
                                viewBox="0 0 22 22"
                                fill="none"
                                xmlns="http://www.w3.org/2000/svg"
                                className="absolute bottom-4 start-4 h-5 w-5 rounded-full"
                            >
                                <rect width="22" height="22" rx="11" fill="white" />
                                <path fillRule="evenodd" clipRule="evenodd" d="M0 0H13.2V10.2667H0V0Z" fill="#1A47B8" />
                                <path
                                    fillRule="evenodd"
                                    clipRule="evenodd"
                                    d="M13.2 0V1.46667H30.8V0H13.2ZM13.2 2.93333V4.4H30.8V2.93333H13.2ZM13.2 5.86667V7.33333H30.8V5.86667H13.2ZM13.2 8.8V10.2667H30.8V8.8H13.2ZM0 11.7333V13.2H30.8V11.7333H0ZM0 14.6667V16.1333H30.8V14.6667H0ZM0 17.6V19.0667H30.8V17.6H0ZM0 20.5333V22H30.8V20.5333H0Z"
                                    fill="#F93939"
                                />
                                <path
                                    fillRule="evenodd"
                                    clipRule="evenodd"
                                    d="M1.46667 1.46667V2.93333H2.93334V1.46667H1.46667ZM4.40001 1.46667V2.93333H5.86667V1.46667H4.40001ZM7.33334 1.46667V2.93333H8.80001V1.46667H7.33334ZM10.2667 1.46667V2.93333H11.7333V1.46667H10.2667ZM8.80001 2.93333V4.4H10.2667V2.93333H8.80001ZM5.86667 2.93333V4.4H7.33334V2.93333H5.86667ZM2.93334 2.93333V4.4H4.40001V2.93333H2.93334ZM1.46667 4.4V5.86667H2.93334V4.4H1.46667ZM4.40001 4.4V5.86667H5.86667V4.4H4.40001ZM7.33334 4.4V5.86667H8.80001V4.4H7.33334ZM10.2667 4.4V5.86667H11.7333V4.4H10.2667ZM1.46667 7.33333V8.8H2.93334V7.33333H1.46667ZM4.40001 7.33333V8.8H5.86667V7.33333H4.40001ZM7.33334 7.33333V8.8H8.80001V7.33333H7.33334ZM10.2667 7.33333V8.8H11.7333V7.33333H10.2667ZM8.80001 5.86667V7.33333H10.2667V5.86667H8.80001ZM5.86667 5.86667V7.33333H7.33334V5.86667H5.86667ZM2.93334 5.86667V7.33333H4.40001V5.86667H2.93334Z"
                                    fill="white"
                                />
                            </svg>
                        </div>
                    </div>

                    <div className="pb-1 pt-3 text-center text-slate-800 dark:text-white">
                        <h2 className="text-[22px]/tight font-bold tracking-tight">James Sporty</h2>
                        <div className="text-sm">Forward</div>
                    </div>
                </div>

                <div className="mx-auto grid w-fit grid-cols-3 divide-x divide-custom-gray-200 py-5 text-slate-800 dark:divide-custom-gray-600 dark:text-white">
                    {statistics.map((statistic) => (
                        <div key={statistic.label} className="px-7 text-center">
                            <div className="mb-2 text-sm/tight font-bold">{statistic.value}</div>
                            <div className="text-[0.6875rem]/tight uppercase">{statistic.label}</div>
                        </div>
                    ))}
                </div>
            </div>

            <svg className="invisible absolute" width="0" height="0" xmlns="http://www.w3.org/2000/svg" version="1.1">
                <defs>
                    <filter id="rounded">
                        <feGaussianBlur in="SourceGraphic" stdDeviation="9" result="blur" />
                        <feColorMatrix in="blur" mode="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 19 -9" result="goo" />
                        <feComposite in="SourceGraphic" in2="goo" operator="atop" />
                    </filter>
                </defs>
            </svg>
        </div>
    );
}
