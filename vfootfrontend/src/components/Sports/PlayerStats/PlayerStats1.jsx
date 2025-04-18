const metrics = [
    {
        label: 'From',
        value: 'Portland, OR',
    },
    {
        label: 'Birthdate',
        value: 'Dec 27, 1999',
    },
    {
        label: 'Nationality',
        value: 'United States',
    },
    {
        label: 'Experience',
        value: '4th Season',
    },
];

const statistics = [
    {
        label: 'Years',
        value: 22,
    },
    {
        label: 'Position',
        value: 'FW',
    },
    {
        label: 'Height',
        value: '6\'5"',
    },
    {
        label: 'Weight (lbs)',
        value: 195,
    },
    {
        label: 'Shirt #',
        value: 26,
    },
    {
        label: 'Games',
        value: 81,
    },
];

export default function PlayerStats1() {
    return (
        <div className="mx-auto w-full max-w-[1460px] px-5">
            <div className="rounded-3xl border border-custom-gray-200 bg-team-golden-primary dark:border-custom-gray-600">
                <div className="grid min-h-[340px] gap-y-12 px-6 py-8 md:grid-cols-[35%_1fr_auto] md:gap-x-6 md:py-0 md:pe-5 md:ps-0 lg:gap-x-0">
                    <div className="relative order-3 -mx-6 -mb-8 -mt-5 h-[340px] overflow-hidden md:order-none md:mx-0 md:mb-0 md:h-auto">
                        <div className="relative isolate mt-5 flex h-full overflow-hidden ps-5">
                            <svg
                                viewBox="0 0 420 420"
                                fill="none"
                                xmlns="http://www.w3.org/2000/svg"
                                className="absolute start-1/2 top-10 -z-10 hidden h-auto w-full -translate-x-1/2 text-team-golden-primary [filter:drop-shadow(0_0_60px_#FF9000)] md:w-4/5 lg:block lg:w-[300px] xl:h-[420px] xl:w-[420px]"
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
                        <img
                            src="https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-1.png"
                            alt="Player"
                            className="absolute start-1/2 top-0 max-w-[360px] -translate-x-1/2 lg:max-w-[480px]"
                        />
                    </div>
                    <div className="order-1 mx-auto md:order-none md:mx-0 md:py-12">
                        <h2 className="mb-4 flex flex-col items-center text-xl font-extrabold tracking-tighter text-white md:items-start lg:text-2xl xl:text-[2.5rem]/none">
                            <span>James</span>
                            <span className="-mt-2 text-5xl tracking-[-0.06em] lg:text-6xl xl:text-[5.125rem]/none">Sporty</span>
                        </h2>
                        <div className="mb-5 flex items-start justify-center gap-1.5 md:mb-10 md:justify-start">
                            <span className="inline-flex rounded-full bg-custom-yellow-300 px-3 py-1 text-xs/none font-extrabold uppercase tracking-[0.2em] text-custom-gray-900">
                                Forward
                            </span>
                            <span className="inline-flex items-center gap-x-1.5 rounded-full bg-custom-gray-900 px-3 py-1 text-xs/none font-extrabold uppercase tracking-[0.2em] text-white">
                                <span className="aspect-square w-1.5 rounded-full border-2 border-custom-green"></span>
                                Active
                            </span>
                        </div>
                        <div className="flex items-center justify-center gap-x-2 md:justify-start">
                            <div className="inline-flex aspect-square w-7 items-center justify-center rounded-full border border-custom-gray-200 bg-white md:w-10">
                                <svg
                                    viewBox="0 0 420 420"
                                    fill="none"
                                    xmlns="http://www.w3.org/2000/svg"
                                    className="h-4 w-4 text-team-golden-primary md:h-5 md:w-5"
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
                            <div className="text-base font-extrabold text-white md:text-xl/tight">Golden Team</div>
                        </div>
                    </div>
                    <div className="order-2 grid grid-cols-2 items-baseline gap-x-4 gap-y-4 self-center uppercase text-white sm:grid-cols-4 md:order-none md:grid-cols-1 md:gap-y-1 md:py-12 md:pe-8 lg:grid-cols-2 lg:gap-y-8 xl:pe-14">
                        {metrics.map((metric) => (
                            <div key={metric.label} className="contents">
                                <div className="text-end text-xs/tight md:text-start">{metric.label}</div>
                                <div className="text-sm/tight font-extrabold md:mb-3 lg:mb-0 lg:text-base/tight">{metric.value}</div>
                            </div>
                        ))}
                    </div>
                </div>
                <div className="rounded-3xl bg-white py-10 ring-1 ring-custom-gray-200 dark:bg-custom-gray-800 dark:ring-custom-gray-600">
                    <div className="grid grid-cols-3 gap-y-5 px-6 sm:px-8 md:grid-cols-[repeat(auto-fit,minmax(90px,1fr))] md:px-0">
                        {statistics.map((statistic) => (
                            <div
                                key={statistic.label}
                                className="group relative flex flex-1 flex-col items-center gap-y-1.5 uppercase text-custom-gray-900 dark:text-white"
                            >
                                <div className="text-sm font-bold sm:text-xl/tight md:text-2xl/tight lg:text-[1.75rem]/tight">{statistic.value}</div>
                                <div className="text-[0.6875rem]/tight">{statistic.label}</div>
                                <div className="absolute inset-y-2 end-0 hidden w-px bg-custom-gray-200 group-last:hidden dark:bg-custom-gray-600 md:block"></div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
}
